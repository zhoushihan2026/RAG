"""
TDD 测试: MetadataFilteredRetriever 单例缓存 + QuestionsProcessor/LLM处理器复用

对应 spec: spec/retriever-cache-spec.md
"""
import json
import pickle
import threading
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.retrieval import MetadataFilteredRetriever, DashScopeEmbedding


# ============================================================
# 辅助函数：创建测试用索引文件
# ============================================================

def _setup_index_files(tmp_path, chunks=None, metadata=None):
    """在临时目录中创建 FAISS/BM25/chunks/metadata 文件"""
    vector_db_dir = tmp_path / "vector_dbs"
    vector_db_dir.mkdir(parents=True, exist_ok=True)
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    bm25_db_dir = tmp_path / "bm25_dbs"
    bm25_db_dir.mkdir(parents=True, exist_ok=True)

    chunks = chunks or []
    metadata = metadata or []

    metadata_path = tmp_path / "chunks_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')

    doc_data = {"metainfo": {"file_name": "test.md"}, "content": {"chunks": chunks, "pages": []}}
    (documents_dir / "test.json").write_text(json.dumps(doc_data, ensure_ascii=False), encoding='utf-8')

    import faiss
    dim = 1024
    n = max(len(chunks), 1)
    index = faiss.IndexFlatIP(dim)
    vectors = np.random.randn(n, dim).astype(np.float32)
    faiss.normalize_L2(vectors)
    index.add(vectors)
    faiss.write_index(index, str(vector_db_dir / "all_docs.faiss"))

    from rank_bm25 import BM25Okapi
    tokenized = [c.get("text", "").split() for c in chunks] if chunks else [["dummy"]]
    bm25 = BM25Okapi(tokenized)
    with open(bm25_db_dir / "all_docs.pkl", 'wb') as f:
        pickle.dump(bm25, f)

    return vector_db_dir, documents_dir, bm25_db_dir, metadata_path


# ============================================================
# T-CACHE-01: 相同参数返回同一实例
# ============================================================

class TestRetrieverSingleton:

    def test_same_params_returns_same_instance(self, tmp_path):
        """T-CACHE-01: 相同参数调用 get_instance 返回同一实例"""
        # 先清理缓存
        MetadataFilteredRetriever.clear_cache()

        vector_db_dir, documents_dir, bm25_db_dir, metadata_path = _setup_index_files(tmp_path)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            r1 = MetadataFilteredRetriever.get_instance(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )
            r2 = MetadataFilteredRetriever.get_instance(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )

        assert r1 is r2

    def test_different_params_returns_different_instance(self, tmp_path):
        """T-CACHE-02: 不同参数返回不同实例"""
        MetadataFilteredRetriever.clear_cache()

        vector_db_dir, documents_dir, bm25_db_dir, metadata_path = _setup_index_files(tmp_path)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            r1 = MetadataFilteredRetriever.get_instance(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )
            r2 = MetadataFilteredRetriever.get_instance(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.8
            )

        assert r1 is not r2

    def test_clear_cache_forces_reload(self, tmp_path):
        """T-CACHE-03: clear_cache 后下次 get_instance 重新加载"""
        MetadataFilteredRetriever.clear_cache()

        vector_db_dir, documents_dir, bm25_db_dir, metadata_path = _setup_index_files(tmp_path)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            r1 = MetadataFilteredRetriever.get_instance(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )
            MetadataFilteredRetriever.clear_cache()
            r2 = MetadataFilteredRetriever.get_instance(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )

        assert r1 is not r2

    def test_first_call_initializes_normally(self, tmp_path):
        """T-CACHE-04: 首次调用正常初始化，行为与直接构造一致"""
        MetadataFilteredRetriever.clear_cache()

        chunks = [{"text": "测试内容", "page": 1, "source_file": "test.md"}]
        metadata = [{"company": "公司A", "broker": "", "doc_type": "年报"}]
        vector_db_dir, documents_dir, bm25_db_dir, metadata_path = _setup_index_files(tmp_path, chunks, metadata)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            r = MetadataFilteredRetriever.get_instance(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )

        # 验证初始化结果与直接构造一致
        assert len(r.all_chunks) == 1
        assert len(r.all_metadata) == 1
        assert r.all_metadata[0]["company"] == "公司A"

    def test_concurrent_access_single_instance(self, tmp_path):
        """T-CACHE-05: 并发请求只创建一个实例"""
        MetadataFilteredRetriever.clear_cache()

        vector_db_dir, documents_dir, bm25_db_dir, metadata_path = _setup_index_files(tmp_path)
        results = []
        barrier = threading.Barrier(3)

        def get_retriever():
            barrier.wait()
            with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
                r = MetadataFilteredRetriever.get_instance(
                    vector_db_dir=vector_db_dir,
                    documents_dir=documents_dir,
                    bm25_db_dir=bm25_db_dir,
                    metadata_path=metadata_path,
                    alpha=0.5
                )
                results.append(r)

        threads = [threading.Thread(target=get_retriever) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有线程应拿到同一实例
        assert all(r is results[0] for r in results)

    def test_direct_init_still_works(self, tmp_path):
        """T-CACHE-06: 直接构造 MetadataFilteredRetriever 仍然可用"""
        MetadataFilteredRetriever.clear_cache()

        vector_db_dir, documents_dir, bm25_db_dir, metadata_path = _setup_index_files(tmp_path)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            r = MetadataFilteredRetriever(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )

        assert r.faiss_index is not None
        assert r.bm25_index is not None


# ============================================================
# T-CACHE-07: QuestionsProcessor 复用
# ============================================================

class TestProcessorReuse:

    def test_pipeline_reuses_processor(self, tmp_path):
        """T-CACHE-07: RAGPipeline 内复用 QuestionsProcessor"""
        from src.pipeline import Pipeline

        pipeline = Pipeline(root_path=tmp_path)

        with patch.object(pipeline, '_create_processor') as mock_create:
            mock_processor = MagicMock()
            mock_create.return_value = mock_processor

            # 第一次调用
            p1 = pipeline._get_or_create_processor()
            # 第二次调用
            p2 = pipeline._get_or_create_processor()

        assert p1 is p2
        assert mock_create.call_count == 1

    def test_pipeline_reuses_llm_processor(self, tmp_path):
        """T-CACHE-08: _get_llm_processor 每次创建新实例（避免多线程并发共享客户端）"""
        from src.pipeline import Pipeline

        pipeline = Pipeline(root_path=tmp_path)

        with patch('src.api_requests.Fe8Processor') as mock_fe8:
            mock_fe8.side_effect = [MagicMock(), MagicMock()]
            pipeline.run_config.api_provider = "fe8"

            p1 = pipeline._get_llm_processor()
            p2 = pipeline._get_llm_processor()

        # 每次调用应创建新实例（不缓存，避免并发线程共享 httpx.Client）
        assert p1 is not p2
        assert mock_fe8.call_count == 2
