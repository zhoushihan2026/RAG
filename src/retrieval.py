import json
import logging
import tempfile
import shutil
import os
from typing import List, Tuple, Dict, Union
from rank_bm25 import BM25Okapi
import pickle
from pathlib import Path
import faiss
import numpy as np
from src.reranking import LLMReranker, LocalReranker
import hashlib
import pandas as pd
import time

_log = logging.getLogger(__name__)

class DashScopeEmbedding:
    """基于DashScope API的Embedding模型（text-embedding-v4）"""
    
    _client = None
    _model_name = "text-embedding-v4"
    
    def __init__(self):
        if DashScopeEmbedding._client is None:
            from openai import OpenAI
            
            api_key = os.getenv("DASHSCOPE_API_KEY")
            if not api_key:
                raise ValueError("请设置环境变量 DASHSCOPE_API_KEY")
            
            DashScopeEmbedding._client = OpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            
            print(f"[DashScopeEmbedding] 初始化成功，使用模型: {self._model_name}")
    
    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False, batch_size=None):
        """编码文本为向量（兼容sentence_transformers接口）"""
        if isinstance(texts, str):
            texts = [texts]
        
        all_embeddings = []
        
        for i in range(0, len(texts), 6):
            batch = texts[i:i+6]
            
            try:
                response = DashScopeEmbedding._client.embeddings.create(
                    model=self._model_name,
                    input=batch,
                    dimensions=1024
                )
                
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
                
            except Exception as e:
                print(f"[DashScopeEmbedding] API调用失败: {e}")
                raise
        
        result = np.array(all_embeddings)
        
        if normalize_embeddings:
            norms = np.linalg.norm(result, axis=1, keepdims=True)
            norms[norms == 0] = 1
            result = result / norms
        
        return result

class BM25Retriever:
    def __init__(self, bm25_db_dir: Path, documents_dir: Path):
        # 初始化BM25检索器，指定BM25索引和文档目录
        self.bm25_db_dir = bm25_db_dir
        self.documents_dir = documents_dir
        
    def retrieve_by_company_name(self, company_name: str, query: str, top_n: int = 3, return_parent_pages: bool = False) -> List[Dict]:
        # 按公司名检索相关文本块，返回BM25分数最高的top_n个块
        # 同一公司的所有PDF已合并到同一个BM25索引中
        bm25_path = self.bm25_db_dir / f"{company_name}.pkl"
        if not bm25_path.exists():
            raise ValueError(f"No BM25 index found for company '{company_name}'.")

        with open(bm25_path, 'rb') as f:
            bm25_index = pickle.load(f)

        # 合并同公司所有文档的chunks和pages
        all_chunks = []
        all_pages = []
        chunk_file_map = []
        for path in self.documents_dir.glob("*.json"):
            with open(path, 'r', encoding='utf-8') as f:
                doc = json.load(f)
            if "metainfo" not in doc or "content" not in doc:
                continue
            if doc["metainfo"].get("company_name") == company_name:
                file_name = doc["metainfo"].get("file_name", "")
                num_chunks = len(doc["content"]["chunks"])
                all_chunks.extend(doc["content"]["chunks"])
                all_pages.extend(doc["content"]["pages"])
                chunk_file_map.extend([file_name] * num_chunks)

        if not all_chunks:
            raise ValueError(f"No chunks found for company '{company_name}'.")

        tokenized_query = query.split()
        scores = bm25_index.get_scores(tokenized_query).tolist()

        actual_top_n = min(top_n, len(scores))
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:actual_top_n]

        retrieval_results = []
        seen_pages = set()

        for index in top_indices:
            score = round(float(scores[index]), 4)
            chunk = all_chunks[index]
            source_file = chunk_file_map[index] if index < len(chunk_file_map) else ""
            parent_page = next((page for page in all_pages if page["page"] == chunk["page"]), None)

            if return_parent_pages and parent_page:
                if parent_page["page"] not in seen_pages:
                    seen_pages.add(parent_page["page"])
                    result = {
                        "distance": score,
                        "page": parent_page["page"],
                        "text": parent_page["text"],
                        "file_name": source_file
                    }
                    retrieval_results.append(result)
            else:
                result = {
                    "distance": score,
                    "page": chunk["page"],
                    "text": chunk["text"],
                    "file_name": source_file
                }
                retrieval_results.append(result)

        return retrieval_results



EMBEDDING_MODEL_PATH = "/root/autodl-tmp/embedding/Qwen/Qwen3-Embedding-4B"


class VectorRetriever:
    _model = None

    def __init__(self, vector_db_dir: Path, documents_dir: Path):
        self.vector_db_dir = vector_db_dir
        self.documents_dir = documents_dir
        self.all_dbs = self._load_dbs()
        if VectorRetriever._model is None:
            VectorRetriever._model = DashScopeEmbedding()

    def _get_embedding(self, text: str):
        return VectorRetriever._model.encode(
            [text],
            normalize_embeddings=True,
            show_progress_bar=False
        )[0].tolist()

    @staticmethod
    def get_strings_cosine_similarity(str1, str2):
        if VectorRetriever._model is None:
            VectorRetriever._model = DashScopeEmbedding()
        embeddings = VectorRetriever._model.encode(
            [str1, str2],
            normalize_embeddings=True,
            show_progress_bar=False
        )
        embedding1 = embeddings[0]
        embedding2 = embeddings[1]
        similarity_score = np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))
        similarity_score = round(float(similarity_score), 4)
        return similarity_score

    def _load_dbs(self):
        # 按company_name加载向量库和对应文档
        # 同一公司的所有PDF已合并到同一个FAISS索引中
        all_dbs = []
        all_documents_paths = list(self.documents_dir.glob('*.json'))

        # 按 company_name 分组文档
        company_docs = {}
        for document_path in all_documents_paths:
            try:
                with open(document_path, 'r', encoding='utf-8') as f:
                    document = json.load(f)
            except Exception as e:
                _log.error(f"Error loading JSON from {document_path.name}: {e}")
                continue
            company_name = document.get('metainfo', {}).get('company_name', None)
            if not company_name:
                _log.warning(f"No company_name found in metainfo for document {document_path.name}")
                continue
            if company_name not in company_docs:
                company_docs[company_name] = []
            company_docs[company_name].append(document)

        for company_name, documents in company_docs.items():
            faiss_path = self.vector_db_dir / f"{company_name}.faiss"
            if not faiss_path.exists():
                _log.warning(f"No matching vector DB found for company '{company_name}'")
                continue
            try:
                with tempfile.NamedTemporaryFile(suffix='.faiss', delete=False) as tmp:
                    tmp_path = tmp.name
                shutil.copy2(str(faiss_path), tmp_path)
                vector_db = faiss.read_index(tmp_path)
                os.remove(tmp_path)
            except Exception as e:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                _log.error(f"Error reading vector DB for company '{company_name}': {e}")
                continue

            # 合并同公司所有文档的chunks和pages，同时记录每个chunk的来源文件
            merged_chunks = []
            merged_pages = []
            merged_chunk_file_map = []
            for doc in documents:
                file_name = doc["metainfo"].get("file_name", "")
                num_chunks = len(doc["content"].get("chunks", []))
                merged_chunks.extend(doc["content"].get("chunks", []))
                merged_pages.extend(doc["content"].get("pages", []))
                merged_chunk_file_map.extend([file_name] * num_chunks)

            merged_document = {
                "metainfo": {
                    "company_name": company_name,
                },
                "content": {
                    "chunks": merged_chunks,
                    "pages": merged_pages,
                    "chunk_file_map": merged_chunk_file_map
                }
            }
            report = {
                "name": company_name,
                "vector_db": vector_db,
                "document": merged_document
            }
            all_dbs.append(report)
        return all_dbs

    def retrieve_by_company_name(self, company_name: str, query: str, llm_reranking_sample_size: int = None, top_n: int = 3, return_parent_pages: bool = False) -> List[Tuple[str, float]]:
        # 按公司名检索相关文本块，返回向量距离最近的top_n个块
        # 同一公司的所有PDF已合并到同一个FAISS索引中
        target_report = None
        for report in self.all_dbs:
            if report["name"] == company_name:
                target_report = report
                break
        if not target_report:
            _log.error(f"No vector DB found for company '{company_name}'.")
            raise ValueError(f"No vector DB found for company '{company_name}'.")

        document = target_report["document"]
        vector_db = target_report["vector_db"]
        chunks = document["content"]["chunks"]
        pages = document["content"].get("pages", [])
        chunk_file_map = document["content"].get("chunk_file_map", [])
        actual_top_n = min(top_n, len(chunks))
        if actual_top_n <= 0:
            return []
        embedding = self._get_embedding(query)
        embedding_array = np.array(embedding, dtype=np.float32).reshape(1, -1)
        distances, indices = vector_db.search(x=embedding_array, k=actual_top_n)

        retrieval_results = []
        seen_pages = set()
        for distance, index in zip(distances[0], indices[0]):
            distance = round(float(distance), 4)
            chunk = chunks[index]
            source_file = chunk_file_map[index] if index < len(chunk_file_map) else ""
            parent_page = None
            if pages:
                parent_page = next((page for page in pages if page["page"] == chunk.get("page")), None)
            if return_parent_pages and parent_page:
                if parent_page["page"] not in seen_pages:
                    seen_pages.add(parent_page["page"])
                    result = {
                        "distance": distance,
                        "page": parent_page["page"],
                        "text": parent_page["text"],
                        "file_name": source_file
                    }
                    retrieval_results.append(result)
            else:
                result = {
                    "distance": distance,
                    "page": chunk.get("page", 0),
                    "text": chunk["text"],
                    "file_name": source_file
                }
                retrieval_results.append(result)

        return retrieval_results

    def retrieve_all(self, company_name: str) -> List[Dict]:
        # 检索公司所有文本块，返回全部内容
        # 同一公司的所有PDF已合并到同一个FAISS索引中
        target_report = None
        for report in self.all_dbs:
            if report["name"] == company_name:
                target_report = report
                break
        if not target_report:
            _log.error(f"No vector DB found for company '{company_name}'.")
            raise ValueError(f"No vector DB found for company '{company_name}'.")

        document = target_report["document"]
        pages = document["content"]["pages"]
        chunk_file_map = document["content"].get("chunk_file_map", [])
        # 建立 page -> file_name 映射
        page_to_file = {}
        chunks = document["content"]["chunks"]
        for i, chunk in enumerate(chunks):
            page = chunk.get("page", 0)
            if page not in page_to_file and i < len(chunk_file_map):
                page_to_file[page] = chunk_file_map[i]

        all_pages = []
        for page in sorted(pages, key=lambda p: p["page"]):
            result = {
                "distance": 0.5,
                "page": page["page"],
                "text": page["text"],
                "file_name": page_to_file.get(page["page"], "")
            }
            all_pages.append(result)

        return all_pages


class HybridRetriever:
    def __init__(self, vector_db_dir: Path, documents_dir: Path):
        self.vector_retriever = VectorRetriever(vector_db_dir, documents_dir)
        self.reranker = LLMReranker()
        
    def retrieve_by_company_name(
        self, 
        company_name: str, 
        query: str, 
        llm_reranking_sample_size: int = 28,
        documents_batch_size: int = 10,
        top_n: int = 6,
        llm_weight: float = 0.7,
        return_parent_pages: bool = False
    ) -> List[Dict]:
        """
        使用混合检索方法进行检索和重排。
        
        参数：
            company_name: 需要检索的公司名称
            query: 检索查询语句
            llm_reranking_sample_size: 首轮向量检索返回的候选数量
            documents_batch_size: 每次送入LLM重排的文档数
            top_n: 最终返回的重排结果数量
            llm_weight: LLM分数权重（0-1）
            return_parent_pages: 是否返回完整页面（而非分块）
        
        返回：
            经过重排的文档字典列表，包含分数
        """
        t0 = time.time()
        # 首先用向量检索器获取初步结果
        print("[计时] [HybridRetriever] 开始向量检索 ...")
        vector_results = self.vector_retriever.retrieve_by_company_name(
            company_name=company_name,
            query=query,
            top_n=llm_reranking_sample_size,
            return_parent_pages=return_parent_pages
        )
        t1 = time.time()
        print(f"[计时] [HybridRetriever] 向量检索耗时: {t1-t0:.2f} 秒")
        # 使用LLM对结果进行重排
        print("[计时] [HybridRetriever] 开始LLM重排 ...")
        reranked_results = self.reranker.rerank_documents(
            query=query,
            documents=vector_results,
            documents_batch_size=documents_batch_size,
            llm_weight=llm_weight
        )
        t2 = time.time()
        print(f"[计时] [HybridRetriever] LLM重排耗时: {t2-t1:.2f} 秒")
        print(f"[计时] [HybridRetriever] 总耗时: {t2-t0:.2f} 秒")
        return reranked_results[:top_n]


class HybridBM25VectorRetriever:
    """混合检索器: BM25稀疏检索 + Vector稠密检索 + DashScope Rerank精排，无需LLM参与"""

    def __init__(self, vector_db_dir: Path, documents_dir: Path, bm25_db_dir: Path, alpha: float = 0.5):
        """
        参数：
            vector_db_dir: 向量数据库目录
            documents_dir: 分块文档目录
            bm25_db_dir: BM25索引目录
            alpha: 向量检索权重（0-1），1-alpha为BM25权重，默认0.5
        """
        self.vector_retriever = VectorRetriever(vector_db_dir, documents_dir)
        self.bm25_retriever = BM25Retriever(bm25_db_dir, documents_dir)
        self.reranker = LocalReranker()
        self.alpha = alpha

    def _normalize_scores(self, results: List[Dict], higher_is_better: bool = True) -> List[Dict]:
        """将分数归一化到0-1范围"""
        if not results:
            return results
        scores = [r["distance"] for r in results]
        min_s = min(scores)
        max_s = max(scores)
        range_s = max_s - min_s if max_s != min_s else 1.0
        for r in results:
            normalized = (r["distance"] - min_s) / range_s
            if not higher_is_better:
                normalized = 1.0 - normalized
            r["normalized_score"] = round(normalized, 6)
        return results

    def retrieve_by_company_name(
        self,
        company_name: str,
        query: str,
        top_n: int = 6,
        recall_n: int = 30,
        return_parent_pages: bool = False
    ) -> List[Dict]:
        """
        使用BM25+Vector混合召回 + DashScope Rerank精排。
        参数：
            company_name: 需要检索的公司名称
            query: 检索查询语句
            top_n: 最终返回的结果数量
            recall_n: 首轮混合召回的候选数量
            return_parent_pages: 是否返回完整页面（而非分块）
        返回：
            经过rerank精排的文档字典列表
        """
        t0 = time.time()

        # 第一阶段: 分别用BM25和Vector检索
        print("[计时] [HybridBM25VectorRetriever] 开始BM25检索 ...")
        bm25_results = self.bm25_retriever.retrieve_by_company_name(
            company_name=company_name,
            query=query,
            top_n=recall_n,
            return_parent_pages=return_parent_pages
        )
        t1 = time.time()
        print(f"[计时] [HybridBM25VectorRetriever] BM25检索耗时: {t1-t0:.2f} 秒, 召回 {len(bm25_results)} 条")

        print("[计时] [HybridBM25VectorRetriever] 开始向量检索 ...")
        vector_results = self.vector_retriever.retrieve_by_company_name(
            company_name=company_name,
            query=query,
            top_n=recall_n,
            return_parent_pages=return_parent_pages
        )
        t2 = time.time()
        print(f"[计时] [HybridBM25VectorRetriever] 向量检索耗时: {t2-t1:.2f} 秒, 召回 {len(vector_results)} 条")

        # 第二阶段: 分数归一化 + 加权融合
        # BM25分数: 越大越相关 (higher_is_better=True)
        # Vector距离: 越小越相关 (higher_is_better=False)
        bm25_results = self._normalize_scores(bm25_results, higher_is_better=True)
        vector_results = self._normalize_scores(vector_results, higher_is_better=False)

        # 用text去重，合并两路结果
        merged = {}
        for r in bm25_results:
            key = r["text"]
            if key not in merged:
                merged[key] = r.copy()
                merged[key]["hybrid_score"] = (1 - self.alpha) * r["normalized_score"]
            else:
                merged[key]["hybrid_score"] += (1 - self.alpha) * r["normalized_score"]

        for r in vector_results:
            key = r["text"]
            if key not in merged:
                merged[key] = r.copy()
                merged[key]["hybrid_score"] = self.alpha * r["normalized_score"]
            else:
                merged[key]["hybrid_score"] += self.alpha * r["normalized_score"]

        # 按hybrid_score降序排序，取前recall_n个作为rerank候选
        candidates = sorted(merged.values(), key=lambda x: x["hybrid_score"], reverse=True)[:recall_n]
        t3 = time.time()
        print(f"[计时] [HybridBM25VectorRetriever] 混合融合耗时: {t3-t2:.2f} 秒, 候选 {len(candidates)} 条")

        # 第三阶段: DashScope Rerank精排
        print("[计时] [HybridBM25VectorRetriever] 开始DashScope Rerank精排 ...")
        reranked_results = self.reranker.rerank(
            query=query,
            documents=candidates,
            top_n=top_n
        )
        t4 = time.time()
        print(f"[计时] [HybridBM25VectorRetriever] Rerank精排耗时: {t4-t3:.2f} 秒")
        print(f"[计时] [HybridBM25VectorRetriever] 总耗时: {t4-t0:.2f} 秒")
        return reranked_results


class MetadataFilteredRetriever:
    """
    元数据过滤检索器。
    支持硬过滤、软提升、分级回退机制。
    在筛选后的chunk子集上做BM25+Vector+Rerank检索。
    """

    MIN_RESULTS = 3

    def __init__(self, vector_db_dir: Path, documents_dir: Path, bm25_db_dir: Path,
                 metadata_path: Path, alpha: float = 0.5):
        self.vector_db_dir = vector_db_dir
        self.documents_dir = documents_dir
        self.bm25_db_dir = bm25_db_dir
        self.alpha = alpha

        self.faiss_index = self._load_faiss()
        self.bm25_index = self._load_bm25()

        self.all_chunks, self.all_metadata = self._load_chunks_and_metadata(metadata_path)
        self.all_pages = self._load_pages()

        self.reranker = LocalReranker()

    def _load_faiss(self):
        faiss_path = self.vector_db_dir / "all_docs.faiss"
        if not faiss_path.exists():
            raise FileNotFoundError(f"未找到统一向量库: {faiss_path}")
        with tempfile.NamedTemporaryFile(suffix='.faiss', delete=False) as tmp:
            tmp_path = tmp.name
        shutil.copy2(str(faiss_path), tmp_path)
        index = faiss.read_index(tmp_path)
        os.remove(tmp_path)
        return index

    def _load_bm25(self):
        bm25_path = self.bm25_db_dir / "all_docs.pkl"
        if not bm25_path.exists():
            raise FileNotFoundError(f"未找到统一BM25索引: {bm25_path}")
        with open(bm25_path, 'rb') as f:
            return pickle.load(f)

    def _load_chunks_and_metadata(self, metadata_path: Path):
        all_chunks = []
        for path in sorted(self.documents_dir.glob("*.json")):
            with open(path, 'r', encoding='utf-8') as f:
                doc = json.load(f)
            if "content" not in doc:
                continue
            all_chunks.extend(doc["content"].get("chunks", []))

        with open(metadata_path, 'r', encoding='utf-8') as f:
            all_metadata = json.load(f)

        assert len(all_chunks) == len(all_metadata), \
            f"chunks数量({len(all_chunks)})与元数据数量({len(all_metadata)})不一致"

        return all_chunks, all_metadata

    def _load_pages(self):
        all_pages = []
        for path in sorted(self.documents_dir.glob("*.json")):
            with open(path, 'r', encoding='utf-8') as f:
                doc = json.load(f)
            if "metainfo" not in doc or "content" not in doc:
                continue
            source_file = doc["metainfo"].get("file_name", "")
            for page in doc["content"].get("pages", []):
                page["file_name"] = source_file
                all_pages.append(page)
        return all_pages

    # ========== 元数据过滤 ==========

    # soft_doc_type不参与硬过滤，仅用于软加权（LLM推断的doc_type）
    SOFT_ONLY_KEYS = {"soft_doc_type"}

    def _matches_filter(self, meta: dict, filters: dict) -> bool:
        """检查单个chunk的元数据是否匹配过滤条件（doc_type仅软加权，不硬过滤）"""
        for key, value in filters.items():
            if value is None or value == "":
                continue
            if key in self.SOFT_ONLY_KEYS:
                continue
            if str(meta.get(key, "")).strip() != str(value).strip():
                return False
        return True

    def _apply_hard_filter(self, filters: dict):
        """
        硬过滤：返回匹配filter的chunk索引列表。
        返回: (valid_indices, valid_chunks)
        """
        valid_indices = []
        valid_chunks = []
        for i, meta in enumerate(self.all_metadata):
            if self._matches_filter(meta, filters):
                valid_indices.append(i)
                valid_chunks.append(self.all_chunks[i])
        return valid_indices, valid_chunks

    def _build_fallback_chain(self, original_filters: dict) -> List[dict]:
        """
        构建分级回退的filter序列。
        策略：broker比doc_type更精确，应更晚被去掉。
        层级0: company + broker + doc_type（原始条件，不含时间维度）
        层级1: company + broker（去掉doc_type，保留券商）
        层级2: company（仅保留公司）
        层级3: 全空（软过滤）
        """
        chain = [original_filters]

        # 层级1: 去掉doc_type，保留broker
        f1 = {k: v for k, v in original_filters.items() if k != 'doc_type'}
        if f1 != original_filters:
            chain.append(f1)

        # 层级2: 去掉broker，仅保留company
        f2 = {k: v for k, v in f1.items() if k != 'broker'}
        if f2 != f1:
            chain.append(f2)

        # 层级3: 全空（不过滤）-> 触达软过滤
        chain.append({})

        return chain

    def _apply_soft_boost(self, filters: dict):
        """
        软过滤：给所有chunk赋权重，匹配元数据的chunk权重提升。
        soft_doc_type映射到chunk的doc_type字段。
        返回每个chunk的boost权重列表。
        """
        boost_weights = [1.0] * len(self.all_chunks)
        for i, meta in enumerate(self.all_metadata):
            match_count = 0
            for key, value in filters.items():
                if value is None or value == "":
                    continue
                meta_key = key.replace("soft_", "", 1) if key in self.SOFT_ONLY_KEYS else key
                if str(meta.get(meta_key, "")).strip() == str(value).strip():
                    match_count += 1
            if match_count > 0:
                boost_weights[i] = 1.0 + 0.3 * match_count
        return boost_weights

    # ========== 向量检索辅助 ==========

    def _get_embedding(self, text: str):
        if VectorRetriever._model is None:
            VectorRetriever._model = DashScopeEmbedding()
        return VectorRetriever._model.encode(
            [text],
            normalize_embeddings=True,
            show_progress_bar=False
        )[0].tolist()

    # ========== 主检索方法 ==========

    def retrieve(self, rewritten_query: str, metadata_filters: dict,
                 top_n: int = 5, recall_n: int = 30,
                 return_parent_pages: bool = True) -> List[Dict]:
        """
        带分级回退的元数据过滤检索。
        """
        t0 = time.time()
        fallback_chain = self._build_fallback_chain(metadata_filters)

        for level, filters in enumerate(fallback_chain):
            print(f"[检索] 层级{level} 过滤条件: {filters}")

            if not filters:
                # 最后一层：软过滤模式
                print("[检索] 进入软过滤模式")
                return self._do_retrieval_with_boost(rewritten_query, metadata_filters,
                                                     top_n, recall_n, return_parent_pages)

            valid_indices, valid_chunks = self._apply_hard_filter(filters)
            print(f"[检索] 层级{level} 硬过滤结果: {len(valid_chunks)} 条")

            if len(valid_chunks) >= self.MIN_RESULTS:
                print(f"[检索] 层级{level} 结果充足，使用硬过滤结果")
                return self._do_retrieval(rewritten_query, valid_indices, valid_chunks,
                                          top_n, recall_n, return_parent_pages,
                                          soft_filters=metadata_filters)

        # 所有硬过滤级别都不足 -> 软过滤兜底
        print("[检索] 所有硬过滤级别不足，进入软过滤兜底")
        return self._do_retrieval_with_boost(rewritten_query, metadata_filters,
                                             top_n, recall_n, return_parent_pages)

    def _do_retrieval(self, rewritten_query: str, valid_indices: List[int],
                      valid_chunks: List[Dict], top_n: int, recall_n: int,
                      return_parent_pages: bool,
                      soft_filters: dict = None) -> List[Dict]:
        """在筛选后的chunk子集上执行BM25+Vector混合检索+Rerank，支持doc_type软加权"""
        t0 = time.time()

        # 动态构建子集BM25
        tokenized_sub = [c['text'].split() for c in valid_chunks]
        sub_bm25 = BM25Okapi(tokenized_sub)

        # FAISS子集检索：使用IDSelector
        query_embedding = self._get_embedding(rewritten_query)
        query_array = np.array(query_embedding, dtype=np.float32).reshape(1, -1)

        # 创建IDSelector
        id_selector = faiss.IDSelectorBatch(np.array(valid_indices, dtype=np.int64))
        params = faiss.SearchParametersIVF(sel=id_selector) if hasattr(faiss, 'SearchParametersIVF') else faiss.SearchParameters(sel=id_selector)

        actual_k = min(recall_n, len(valid_indices))
        try:
            distances, indices = self.faiss_index.search(query_array, actual_k, params=params)
        except Exception:
            # 如果IDSelector不可用，暴力检索全库再过滤
            distances, indices = self.faiss_index.search(query_array, max(recall_n * 3, len(self.all_chunks)))
            valid_set = set(valid_indices)
            filtered_distances = []
            filtered_indices = []
            for d, idx in zip(distances[0], indices[0]):
                if idx in valid_set:
                    filtered_distances.append(d)
                    filtered_indices.append(idx)
                if len(filtered_indices) >= actual_k:
                    break
            distances = np.array([filtered_distances])
            indices = np.array([filtered_indices])

        # BM25检索
        tokenized_query = rewritten_query.split()
        bm25_scores = sub_bm25.get_scores(tokenized_query)

        # 构建向量检索结果
        vector_results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < len(valid_chunks):
                vector_results.append({
                    "distance": round(float(dist), 4),
                    "page": valid_chunks[idx].get("page", 0),
                    "text": valid_chunks[idx].get("text", ""),
                    "file_name": valid_chunks[idx].get("source_file", "")
                })

        # 构建BM25检索结果
        bm25_top = min(recall_n, len(bm25_scores))
        bm25_top_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:bm25_top]
        bm25_results = []
        for idx in bm25_top_indices:
            bm25_results.append({
                "distance": round(float(bm25_scores[idx]), 4),
                "page": valid_chunks[idx].get("page", 0),
                "text": valid_chunks[idx].get("text", ""),
                "file_name": valid_chunks[idx].get("source_file", "")
            })

        # 分数归一化 + 加权融合
        vector_results = self._normalize_scores(vector_results, higher_is_better=False)
        bm25_results = self._normalize_scores(bm25_results, higher_is_better=True)

        # 计算doc_type软加权（soft_doc_type映射到chunk的doc_type字段）
        boost_map = {}
        if soft_filters:
            for i, chunk in enumerate(valid_chunks):
                boost = 1.0
                for key in self.SOFT_ONLY_KEYS:
                    if key in soft_filters and soft_filters[key]:
                        meta_key = key.replace("soft_", "", 1)
                        if str(chunk.get(meta_key, "")).strip() == str(soft_filters[key]).strip():
                            boost += 0.3
                boost_map[i] = boost

        merged = {}
        for i, r in enumerate(bm25_results):
            key = r["text"]
            boost = boost_map.get(i, 1.0)
            merged[key] = {**r, "hybrid_score": (1 - self.alpha) * r["normalized_score"] * boost}
        for i, r in enumerate(vector_results):
            key = r["text"]
            boost = boost_map.get(i, 1.0)
            if key not in merged:
                merged[key] = {**r, "hybrid_score": self.alpha * r["normalized_score"] * boost}
            else:
                merged[key]["hybrid_score"] += self.alpha * r["normalized_score"] * boost

        candidates = sorted(merged.values(), key=lambda x: x["hybrid_score"], reverse=True)[:recall_n]

        # DashScope Rerank
        reranked = self.reranker.rerank(query=rewritten_query, documents=candidates, top_n=top_n)

        # 替换 chunk text 为完整页面 text（父文档检索）
        if return_parent_pages:
            reranked = self._replace_with_parent_pages(reranked)

        t1 = time.time()
        print(f"[检索] 硬过滤检索总耗时: {t1-t0:.2f} 秒")
        return reranked

    def _do_retrieval_with_boost(self, rewritten_query: str, filters: dict,
                                  top_n: int, recall_n: int,
                                  return_parent_pages: bool) -> List[Dict]:
        """软过滤模式：全库检索，但给匹配元数据的chunk加权重"""
        all_chunks = self.all_chunks
        tokenized_all = [c['text'].split() for c in all_chunks]
        full_bm25 = BM25Okapi(tokenized_all)

        query_embedding = self._get_embedding(rewritten_query)
        query_array = np.array(query_embedding, dtype=np.float32).reshape(1, -1)
        actual_k = min(recall_n, len(all_chunks))
        distances, indices = self.faiss_index.search(query_array, actual_k)

        vector_results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < len(all_chunks):
                vector_results.append({
                    "distance": round(float(dist), 4),
                    "page": all_chunks[idx].get("page", 0),
                    "text": all_chunks[idx].get("text", ""),
                    "file_name": all_chunks[idx].get("source_file", "")
                })

        bm25_scores = full_bm25.get_scores(rewritten_query.split())
        bm25_top = min(recall_n, len(bm25_scores))
        bm25_top_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:bm25_top]
        bm25_results = []
        for idx in bm25_top_indices:
            bm25_results.append({
                "distance": round(float(bm25_scores[idx]), 4),
                "page": all_chunks[idx].get("page", 0),
                "text": all_chunks[idx].get("text", ""),
                "file_name": all_chunks[idx].get("source_file", "")
            })

        vector_results = self._normalize_scores(vector_results, higher_is_better=False)
        bm25_results = self._normalize_scores(bm25_results, higher_is_better=True)

        # 加权融合 + 软提升
        boost_weights = self._apply_soft_boost(filters)
        merged = {}
        for r in bm25_results:
            key = r["text"]
            chunk_idx = self._find_chunk_idx(r["text"])
            boost = boost_weights[chunk_idx] if chunk_idx >= 0 else 1.0
            merged[key] = {**r, "hybrid_score": (1 - self.alpha) * r["normalized_score"] * boost}
        for r in vector_results:
            key = r["text"]
            chunk_idx = self._find_chunk_idx(r["text"])
            boost = boost_weights[chunk_idx] if chunk_idx >= 0 else 1.0
            if key not in merged:
                merged[key] = {**r, "hybrid_score": self.alpha * r["normalized_score"] * boost}
            else:
                merged[key]["hybrid_score"] += self.alpha * r["normalized_score"] * boost

        candidates = sorted(merged.values(), key=lambda x: x["hybrid_score"], reverse=True)[:recall_n]
        reranked = self.reranker.rerank(query=rewritten_query, documents=candidates, top_n=top_n)

        if return_parent_pages:
            reranked = self._replace_with_parent_pages(reranked)

        return reranked

    def _find_chunk_idx(self, text: str) -> int:
        """根据text内容查找chunk在全量列表中的索引"""
        for i, chunk in enumerate(self.all_chunks):
            if chunk.get("text", "") == text:
                return i
        return -1

    def _normalize_scores(self, results: List[Dict], higher_is_better: bool = True) -> List[Dict]:
        if not results:
            return results
        scores = [r["distance"] for r in results]
        min_s = min(scores)
        max_s = max(scores)
        range_s = max_s - min_s if max_s != min_s else 1.0
        for r in results:
            normalized = (r["distance"] - min_s) / range_s
            if not higher_is_better:
                normalized = 1.0 - normalized
            r["normalized_score"] = round(normalized, 6)
        return results

    def _replace_with_parent_pages(self, reranked_results: List[Dict]) -> List[Dict]:
        """将chunk text替换为完整页面text（父文档检索）。
        按 (page, source_file) 联合匹配，避免不同PDF的相同页码冲突。"""
        seen_pages = set()
        result = []
        for item in reranked_results:
            page = item.get("page", 0)
            source_file = item.get("file_name", "")
            page_key = (page, source_file)
            if page_key in seen_pages:
                continue
            seen_pages.add(page_key)
            parent_page = next(
                (p for p in self.all_pages
                 if p.get("page") == page and p.get("file_name", "") == source_file),
                None
            )
            if parent_page:
                item["text"] = parent_page.get("text", item["text"])
            result.append(item)
        return result
