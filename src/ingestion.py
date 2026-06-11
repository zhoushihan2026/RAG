import os
import json
import pickle
import tempfile
import shutil
import time
from typing import List, Union, Dict, Tuple
from pathlib import Path
from tqdm import tqdm
import hashlib

from dotenv import load_dotenv
from openai import OpenAI
from rank_bm25 import BM25Okapi
import faiss
import numpy as np
from src.retrieval import DashScopeEmbedding


def _compute_file_chunks_hash(chunks: list) -> str:
    """计算单份文件chunks的SHA1哈希"""
    sha1 = hashlib.sha1()
    for chunk in chunks:
        text = chunk.get("text", "") if isinstance(chunk, dict) else chunk
        sha1.update(text.encode("utf-8"))
    return sha1.hexdigest()


class BM25Ingestor:
    def __init__(self):
        pass

    def create_bm25_index(self, chunks: List[str]) -> BM25Okapi:
        """从文本块列表创建BM25索引"""
        tokenized_chunks = [chunk.split() for chunk in chunks]
        return BM25Okapi(tokenized_chunks)

    def process_reports(self, all_reports_dir: Path, output_dir: Path):
        """
        将所有报告的chunks合并为统一BM25索引，保存为 all_docs.pkl。
        支持按文件粒度的缓存对比：只有当任意文件变动时才重建索引。
        """
        file_hashes: Dict[str, str] = {}
        all_chunks = []

        for report_path in sorted(all_reports_dir.glob("*.json")):
            with open(report_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            if "content" not in report_data or "chunks" not in report_data.get("content", {}):
                continue
            chunks = report_data["content"]["chunks"]
            all_chunks.extend(chunks)
            file_hashes[report_path.name] = _compute_file_chunks_hash(chunks)

        if not all_chunks:
            print(f"警告：{all_reports_dir} 中没有找到任何chunk数据，无法创建BM25索引。请先执行 report chunk 步骤。")
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        cache_path = output_dir / "bm25_cache.json"
        bm25_file_path = output_dir / "all_docs.pkl"

        cached_hashes = {}
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    cached_hashes = cached.get("file_hashes", {})
            except Exception:
                pass

        if file_hashes == cached_hashes and bm25_file_path.exists():
            print(f"BM25缓存命中，所有文档均未变动，跳过BM25索引构建（已有 {len(all_chunks)} 条）")
            return

        print(f"检测到文档变化，开始全量重建BM25索引（共 {len(all_chunks)} 条）...")

        tokenized_chunks = [chunk['text'].split() for chunk in all_chunks if chunk.get('text')]
        bm25_index = BM25Okapi(tokenized_chunks)
        with open(bm25_file_path, 'wb') as f:
            pickle.dump(bm25_index, f)
        print(f"统一BM25索引已保存到 {bm25_file_path}，共 {len(tokenized_chunks)} 条")

        cache = {
            "file_hashes": file_hashes,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)


class VectorDBIngestor:
    def __init__(self, embedding_batch_size=4):
        self.model = DashScopeEmbedding()
        self.embedding_batch_size = embedding_batch_size

    def _get_embeddings(self, text: Union[str, List[str]]) -> List[float]:
        if isinstance(text, str) and not text.strip():
            raise ValueError("Input text cannot be an empty string.")

        if isinstance(text, list):
            text_chunks = text
        else:
            text_chunks = [text]

        if not all(isinstance(x, str) for x in text_chunks):
            raise ValueError("所有待嵌入文本必须为字符串类型！实际类型: {}".format([type(x) for x in text_chunks]))

        text_chunks = [x for x in text_chunks if x.strip()]
        if not text_chunks:
            raise ValueError("所有待嵌入文本均为空字符串！")
        print('start embedding ================================')
        embeddings = self.model.encode(
            text_chunks,
            normalize_embeddings=True,
            show_progress_bar=True,
            batch_size=self.embedding_batch_size
        )
        return embeddings.tolist()

    def _create_vector_db(self, embeddings: List[float]):
        embeddings_array = np.array(embeddings, dtype=np.float32)
        dimension = len(embeddings[0])
        index = faiss.IndexFlatIP(dimension)
        index.add(embeddings_array)
        return index

    def process_reports(self, all_reports_dir: Path, output_dir: Path):
        """
        将所有报告的chunks合并为统一向量库，支持增量追加：
        - 已有FAISS索引时，只对新增/变更的文档调embedding API，然后追加到已有索引中
        - 无索引或全部变动时，行为与全量模式一致
        同时保存 chunks_metadata.json 供检索时过滤用。
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        faiss_file_path = output_dir / "all_docs.faiss"
        metadata_dir = output_dir.parent
        metadata_path = metadata_dir / "chunks_metadata.json"
        cache_path = output_dir / "embedding_cache.json"

        # 1. 收集当前所有文件的 chunks 和元数据，按文件名记录 hash
        current_files: Dict[str, list] = {}
        current_metadata_by_file: Dict[str, list] = {}

        for report_path in sorted(all_reports_dir.glob("*.json")):
            with open(report_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            if "content" not in report_data or "chunks" not in report_data.get("content", {}):
                continue
            chunks = report_data["content"]["chunks"]
            current_files[report_path.name] = chunks

            file_meta = []
            for chunk in chunks:
                meta = {
                    "company": chunk.get("company", ""),
                    "doc_type": chunk.get("doc_type", ""),
                    "broker": chunk.get("broker", ""),
                    "publish_date": chunk.get("publish_date", ""),
                    "quarter": chunk.get("quarter", ""),
                    "coverage_start": chunk.get("coverage_start", ""),
                    "coverage_end": chunk.get("coverage_end", ""),
                    "industry": chunk.get("industry", ""),
                    "source_file": chunk.get("source_file", ""),
                    "page": chunk.get("page", 0)
                }
                file_meta.append(meta)
            current_metadata_by_file[report_path.name] = file_meta

        if not current_files:
            print(f"警告：{all_reports_dir} 中没有找到任何chunk数据，无法创建向量库。请先执行 report chunk 步骤。")
            return

        # 2. 计算每个文件的 hash
        current_file_hashes: Dict[str, str] = {
            name: _compute_file_chunks_hash(chunks) for name, chunks in current_files.items()
        }

        # 3. 加载缓存中的文件 hash 记录
        cached_file_hashes: Dict[str, str] = {}
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                    cached_file_hashes = cache.get("file_hashes", {})
            except Exception:
                pass

        # 4. 对比找出需要处理的文件（新增 或 hash 变更）
        files_to_process = []
        for fname, fhash in current_file_hashes.items():
            if fname not in cached_file_hashes or cached_file_hashes[fname] != fhash:
                files_to_process.append(fname)

        # 检查是否有被删除的文件
        deleted_files = set(cached_file_hashes.keys()) - set(current_file_hashes.keys())

        # 5. 判断是否需要处理
        need_rebuild = len(files_to_process) > 0 or len(deleted_files) > 0
        has_existing_faiss = faiss_file_path.exists()

        if not need_rebuild and has_existing_faiss:
            total_chunks = sum(len(chunks) for chunks in current_files.values())
            print(f"向量库增量缓存命中，所有文档均未变动，跳过向量库创建（已有 {total_chunks} 个chunks）")
            return

        # 6. 如果没有任何现有索引，或者删除了文件导致无法安全增量 → 全量构建
        if not has_existing_faiss or len(deleted_files) > 0:
            reason = "无现有索引" if not has_existing_faiss else f"检测到 {len(deleted_files)} 个文件被删除"
            print(f"[向量库] {reason}，执行全量构建...")
            self._full_build(current_files, current_metadata_by_file, current_file_hashes,
                            faiss_file_path, metadata_path, cache_path)
            return

        # 7. 增量模式：加载已有索引，只对变动的文件 embedding 后追加
        print(f"[向量库] 增量模式：共 {len(current_files)} 个文件，"
              f"{len(files_to_process)} 个需更新，{len(current_files) - len(files_to_process)} 个复用")

        new_chunks_for_embedding = []
        new_metadata = []

        for fname in files_to_process:
            chunks = current_files[fname]
            new_chunks_for_embedding.extend(
                [chunk['text'][:2048] for chunk in chunks if chunk.get('text')]
            )
            new_metadata.extend(current_metadata_by_file[fname])
            print(f"  + {fname}: {len(chunks)} 个chunks 需重新嵌入")

        if not new_chunks_for_embedding:
            print("[向量库] 无新增内容，仅更新缓存")
            self._save_cache(cache_path, current_file_hashes)
            return

        # 调用 embedding API（仅针对新/变更的 chunks）
        new_embeddings = self._get_embeddings(new_chunks_for_embedding)

        # 加载已有 FAISS 索引并追加
        with tempfile.NamedTemporaryFile(suffix='.faiss', delete=False) as tmp:
            tmp_path = tmp.name
        shutil.copy2(str(faiss_file_path), tmp_path)
        existing_index = faiss.read_index(tmp_path)
        os.remove(tmp_path)

        existing_index.add(np.array(new_embeddings, dtype=np.float32))

        # 写回合并后的索引
        with tempfile.NamedTemporaryFile(suffix='.faiss', delete=False) as tmp:
            tmp_out = tmp.name
        faiss.write_index(existing_index, tmp_out)
        shutil.move(tmp_out, str(faiss_file_path))

        total_after = existing_index.ntotal
        print(f"统一向量库已增量更新到 {faiss_file_path}，总计 {total_after} 个向量 "
              f"(新增 {len(new_embeddings)} 个)")

        # 合并元数据：保留旧的 + 追加新的
        all_metadata = []
        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    old_meta = json.load(f)
                all_metadata = old_meta
            except Exception:
                pass

        all_metadata.extend(new_metadata)

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(all_metadata, f, ensure_ascii=False, indent=2)
        print(f"chunks元数据已更新到 {metadata_path}")

        self._save_cache(cache_path, current_file_hashes)

    def _full_build(self, current_files: Dict[str, list], current_metadata_by_file: Dict[str, list],
                    file_hashes: Dict[str, str], faiss_file_path: Path, metadata_path: Path, cache_path: Path):
        """全量构建向量库（首次运行或删除文件后重建）"""
        all_chunks = []
        all_metadata = []
        for fname in sorted(current_files.keys()):
            chunks = current_files[fname]
            all_chunks.extend(chunks)
            all_metadata.extend(current_metadata_by_file[fname])

        text_chunks = [chunk['text'][:2048] for chunk in all_chunks if chunk.get('text')]
        embeddings = self._get_embeddings(text_chunks)
        index = self._create_vector_db(embeddings)

        with tempfile.NamedTemporaryFile(suffix='.faiss', delete=False) as tmp:
            tmp_path = tmp.name
        faiss.write_index(index, tmp_path)
        shutil.move(tmp_path, str(faiss_file_path))
        print(f"统一向量库已保存到 {faiss_file_path}，共 {len(all_chunks)} 个chunks")

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(all_metadata, f, ensure_ascii=False, indent=2)
        print(f"chunks元数据已保存到 {metadata_path}")

        self._save_cache(cache_path, file_hashes)

    @staticmethod
    def _save_cache(cache_path: Path, file_hashes: Dict[str, str]):
        """保存文件级 hash 缓存"""
        cache = {
            "file_hashes": file_hashes,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
