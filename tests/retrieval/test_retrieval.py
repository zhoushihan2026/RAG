"""
特征测试: 检索行为 (retrieval.py, reranking.py)

锁定行为: S-4.1 ~ S-4.7
"""
import json
import pickle
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.retrieval import (
    MetadataFilteredRetriever,
    DashScopeEmbedding,
)


# ============================================================
# S-4.1 元数据硬过滤
# ============================================================

class TestMetadataHardFilter:
    """锁定 S-4.1: MetadataFilteredRetriever 硬过滤行为"""

    def _create_retriever(self, tmp_path, chunks, metadata, pages=None):
        """辅助: 构造 MetadataFilteredRetriever 实例（mock 外部依赖）"""
        vector_db_dir = tmp_path / "vector_dbs"
        vector_db_dir.mkdir(parents=True, exist_ok=True)
        documents_dir = tmp_path / "documents"
        documents_dir.mkdir(parents=True, exist_ok=True)
        bm25_db_dir = tmp_path / "bm25_dbs"
        bm25_db_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = tmp_path / "chunks_metadata.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')

        doc_data = {
            "metainfo": {"file_name": "test_report.md"},
            "content": {
                "chunks": chunks,
                "pages": pages or [],
            }
        }
        doc_path = documents_dir / "test_report.json"
        doc_path.write_text(json.dumps(doc_data, ensure_ascii=False), encoding='utf-8')

        import faiss
        dim = 1024
        n = len(chunks)
        if n > 0:
            index = faiss.IndexFlatIP(dim)
            vectors = np.random.randn(n, dim).astype(np.float32)
            faiss.normalize_L2(vectors)
            index.add(vectors)
            faiss_path = vector_db_dir / "all_docs.faiss"
            faiss.write_index(index, str(faiss_path))

        from rank_bm25 import BM25Okapi
        tokenized = [c.get("text", "").split() for c in chunks]
        bm25 = BM25Okapi(tokenized) if tokenized else BM25Okapi([["dummy"]])
        bm25_path = bm25_db_dir / "all_docs.pkl"
        with open(bm25_path, 'wb') as f:
            pickle.dump(bm25, f)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None), \
             patch.object(DashScopeEmbedding, 'encode', return_value=np.random.randn(1, 1024).astype(np.float32)):
            retriever = MetadataFilteredRetriever(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )
        return retriever

    def test_hard_filter_company(self, tmp_path):
        """T-RET-01: company 硬过滤只返回匹配 chunk"""
        chunks = [
            {"text": "公司A的内容", "page": 1, "source_file": "a.md"},
            {"text": "公司B的内容", "page": 1, "source_file": "b.md"},
        ]
        metadata = [
            {"company": "公司A", "broker": "", "doc_type": "年报"},
            {"company": "公司B", "broker": "", "doc_type": "年报"},
        ]
        retriever = self._create_retriever(tmp_path, chunks, metadata)

        valid_indices, valid_chunks = retriever._apply_hard_filter({"company": "公司A"})
        assert len(valid_chunks) == 1
        assert valid_chunks[0]["text"] == "公司A的内容"

    def test_hard_filter_multiple_fields(self, tmp_path):
        """company + broker + doc_type 联合过滤"""
        chunks = [
            {"text": "券商研报", "page": 1, "source_file": "a.md"},
            {"text": "年报", "page": 1, "source_file": "b.md"},
        ]
        metadata = [
            {"company": "公司A", "broker": "东方证券", "doc_type": "券商研报"},
            {"company": "公司A", "broker": "", "doc_type": "年报"},
        ]
        retriever = self._create_retriever(tmp_path, chunks, metadata)

        valid_indices, valid_chunks = retriever._apply_hard_filter(
            {"company": "公司A", "broker": "东方证券", "doc_type": "券商研报"}
        )
        assert len(valid_chunks) == 1
        assert valid_chunks[0]["text"] == "券商研报"

    def test_soft_doc_type_not_hard_filtered(self, tmp_path):
        """soft_doc_type 不参与硬过滤"""
        chunks = [
            {"text": "内容1", "page": 1, "source_file": "a.md"},
        ]
        metadata = [
            {"company": "公司A", "broker": "", "doc_type": "年报"},
        ]
        retriever = self._create_retriever(tmp_path, chunks, metadata)

        valid_indices, valid_chunks = retriever._apply_hard_filter(
            {"company": "公司A", "soft_doc_type": "券商研报"}
        )
        assert len(valid_chunks) == 1

    def test_empty_filter_value_skipped(self, tmp_path):
        """空字符串的过滤值被跳过"""
        chunks = [
            {"text": "内容", "page": 1, "source_file": "a.md"},
        ]
        metadata = [
            {"company": "公司A", "broker": "", "doc_type": "年报"},
        ]
        retriever = self._create_retriever(tmp_path, chunks, metadata)

        valid_indices, valid_chunks = retriever._apply_hard_filter(
            {"company": "公司A", "broker": ""}
        )
        assert len(valid_chunks) == 1


# ============================================================
# S-4.2 分级回退
# ============================================================

class TestFallbackChain:
    """锁定 S-4.2: 分级回退机制"""

    def _create_minimal_retriever(self, tmp_path):
        """创建最小 retriever（只测试回退链构建）"""
        vector_db_dir = tmp_path / "vector_dbs"
        vector_db_dir.mkdir(parents=True, exist_ok=True)
        documents_dir = tmp_path / "documents"
        documents_dir.mkdir(parents=True, exist_ok=True)
        bm25_db_dir = tmp_path / "bm25_dbs"
        bm25_db_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = tmp_path / "chunks_metadata.json"
        metadata_path.write_text("[]", encoding='utf-8')

        import faiss
        index = faiss.IndexFlatIP(1024)
        faiss.write_index(index, str(vector_db_dir / "all_docs.faiss"))

        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi([["dummy"]])
        with open(bm25_db_dir / "all_docs.pkl", 'wb') as f:
            pickle.dump(bm25, f)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            retriever = MetadataFilteredRetriever(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )
        return retriever

    def test_fallback_chain_levels(self, tmp_path):
        """T-RET-02: 分级回退 层级0->1->2->3"""
        retriever = self._create_minimal_retriever(tmp_path)

        original_filters = {"company": "公司A", "broker": "东方证券", "doc_type": "券商研报"}
        chain = retriever._build_fallback_chain(original_filters)

        assert chain[0] == {"company": "公司A", "broker": "东方证券", "doc_type": "券商研报"}
        assert chain[1] == {"company": "公司A", "broker": "东方证券"}
        assert chain[2] == {"company": "公司A"}
        assert chain[3] == {}

    def test_min_results_threshold(self, tmp_path):
        """MIN_RESULTS = 3"""
        retriever = self._create_minimal_retriever(tmp_path)
        assert retriever.MIN_RESULTS == 3


# ============================================================
# S-4.3 软加权
# ============================================================

class TestSoftBoost:
    """锁定 S-4.3: 软加权行为"""

    def test_soft_boost_single_match(self, tmp_path):
        """T-RET-03: 匹配一个字段权重 +0.3"""
        chunks = [
            {"text": "内容1", "page": 1, "source_file": "a.md"},
            {"text": "内容2", "page": 1, "source_file": "b.md"},
        ]
        metadata = [
            {"company": "公司A", "doc_type": "年报"},
            {"company": "公司A", "doc_type": "券商研报"},
        ]

        vector_db_dir = tmp_path / "vector_dbs"
        vector_db_dir.mkdir(parents=True, exist_ok=True)
        documents_dir = tmp_path / "documents"
        documents_dir.mkdir(parents=True, exist_ok=True)
        bm25_db_dir = tmp_path / "bm25_dbs"
        bm25_db_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = tmp_path / "chunks_metadata.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')

        doc_data = {"metainfo": {"file_name": "test.md"}, "content": {"chunks": chunks, "pages": []}}
        (documents_dir / "test.json").write_text(json.dumps(doc_data, ensure_ascii=False), encoding='utf-8')

        import faiss
        index = faiss.IndexFlatIP(1024)
        vectors = np.random.randn(2, 1024).astype(np.float32)
        faiss.normalize_L2(vectors)
        index.add(vectors)
        faiss.write_index(index, str(vector_db_dir / "all_docs.faiss"))

        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi([c["text"].split() for c in chunks])
        with open(bm25_db_dir / "all_docs.pkl", 'wb') as f:
            pickle.dump(bm25, f)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            retriever = MetadataFilteredRetriever(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )

        boost_weights = retriever._apply_soft_boost({"doc_type": "年报"})
        assert boost_weights[0] == 1.3
        assert boost_weights[1] == 1.0

    def test_soft_boost_multiple_matches(self, tmp_path):
        """匹配多个字段权重 1.0 + 0.3 * N"""
        metadata = [
            {"company": "公司A", "broker": "东方证券", "doc_type": "券商研报"},
        ]
        metadata_path = tmp_path / "chunks_metadata.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')

        chunks = [{"text": "内容", "page": 1, "source_file": "a.md"}]
        documents_dir = tmp_path / "documents"
        documents_dir.mkdir(parents=True, exist_ok=True)
        doc_data = {"metainfo": {"file_name": "test.md"}, "content": {"chunks": chunks, "pages": []}}
        (documents_dir / "test.json").write_text(json.dumps(doc_data, ensure_ascii=False), encoding='utf-8')

        vector_db_dir = tmp_path / "vector_dbs"
        vector_db_dir.mkdir(parents=True, exist_ok=True)
        bm25_db_dir = tmp_path / "bm25_dbs"
        bm25_db_dir.mkdir(parents=True, exist_ok=True)

        import faiss
        index = faiss.IndexFlatIP(1024)
        vectors = np.random.randn(1, 1024).astype(np.float32)
        faiss.normalize_L2(vectors)
        index.add(vectors)
        faiss.write_index(index, str(vector_db_dir / "all_docs.faiss"))

        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi([["内容"]])
        with open(bm25_db_dir / "all_docs.pkl", 'wb') as f:
            pickle.dump(bm25, f)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            retriever = MetadataFilteredRetriever(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )

        boost_weights = retriever._apply_soft_boost(
            {"company": "公司A", "broker": "东方证券", "doc_type": "券商研报"}
        )
        assert boost_weights[0] == 1.0 + 0.3 * 3  # 1.9


# ============================================================
# S-4.4 分数归一化
# ============================================================

class TestNormalizeScores:
    """锁定 S-4.4: 分数归一化行为"""

    def _create_retriever_for_normalize(self, tmp_path):
        vector_db_dir = tmp_path / "vector_dbs"
        vector_db_dir.mkdir(parents=True, exist_ok=True)
        documents_dir = tmp_path / "documents"
        documents_dir.mkdir(parents=True, exist_ok=True)
        bm25_db_dir = tmp_path / "bm25_dbs"
        bm25_db_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = tmp_path / "chunks_metadata.json"
        metadata_path.write_text("[]", encoding='utf-8')

        import faiss
        index = faiss.IndexFlatIP(1024)
        faiss.write_index(index, str(vector_db_dir / "all_docs.faiss"))

        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi([["dummy"]])
        with open(bm25_db_dir / "all_docs.pkl", 'wb') as f:
            pickle.dump(bm25, f)

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            return MetadataFilteredRetriever(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )

    def test_normalize_higher_is_better(self, tmp_path):
        """T-RET-04: BM25 分数归一化（越高越好）"""
        retriever = self._create_retriever_for_normalize(tmp_path)
        results = [
            {"distance": 10.0},
            {"distance": 5.0},
            {"distance": 0.0},
        ]
        normalized = retriever._normalize_scores(results, higher_is_better=True)
        assert normalized[0]["normalized_score"] == 1.0
        assert normalized[2]["normalized_score"] == 0.0

    def test_normalize_lower_is_better(self, tmp_path):
        """T-RET-04: Vector 分数归一化（距离越小越好，归一化后反转）"""
        retriever = self._create_retriever_for_normalize(tmp_path)
        results = [
            {"distance": 0.1},
            {"distance": 0.5},
            {"distance": 1.0},
        ]
        normalized = retriever._normalize_scores(results, higher_is_better=False)
        assert normalized[0]["normalized_score"] == 1.0
        assert normalized[2]["normalized_score"] == 0.0

    def test_normalize_empty_results(self, tmp_path):
        """空结果不崩溃"""
        retriever = self._create_retriever_for_normalize(tmp_path)
        results = []
        normalized = retriever._normalize_scores(results, higher_is_better=True)
        assert normalized == []

    def test_normalize_single_result(self, tmp_path):
        """单个结果 range_s=0 时归一化为 0"""
        retriever = self._create_retriever_for_normalize(tmp_path)
        results = [{"distance": 5.0}]
        normalized = retriever._normalize_scores(results, higher_is_better=True)
        assert normalized[0]["normalized_score"] == 0.0


# ============================================================
# S-4.5 父文档检索
# ============================================================

class TestParentDocumentRetrieval:
    """锁定 S-4.5: 父文档检索行为"""

    def test_replace_with_parent_pages(self, tmp_path):
        """T-RET-06: chunk text 替换为完整页面 text"""
        vector_db_dir = tmp_path / "vector_dbs"
        vector_db_dir.mkdir(parents=True, exist_ok=True)
        documents_dir = tmp_path / "documents"
        documents_dir.mkdir(parents=True, exist_ok=True)
        bm25_db_dir = tmp_path / "bm25_dbs"
        bm25_db_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = tmp_path / "chunks_metadata.json"
        metadata_path.write_text(json.dumps([{"text": "chunk1", "page": 1, "source_file": "test.md"}]), encoding='utf-8')

        import faiss
        index = faiss.IndexFlatIP(1024)
        faiss.write_index(index, str(vector_db_dir / "all_docs.faiss"))

        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi([["dummy"]])
        with open(bm25_db_dir / "all_docs.pkl", 'wb') as f:
            pickle.dump(bm25, f)

        pages = [
            {"page": 1, "text": "完整第一页内容", "file_name": "test.md"},
            {"page": 2, "text": "完整第二页内容", "file_name": "test.md"},
        ]
        chunks = [
            {"text": "chunk1", "page": 1, "source_file": "test.md"},
        ]
        doc_data = {"metainfo": {"file_name": "test.md"}, "content": {"chunks": chunks, "pages": pages}}
        (documents_dir / "test.json").write_text(json.dumps(doc_data, ensure_ascii=False), encoding='utf-8')

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            retriever = MetadataFilteredRetriever(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )

        reranked = [
            {"page": 1, "file_name": "test.md", "text": "chunk1"},
        ]
        result = retriever._replace_with_parent_pages(reranked)
        assert result[0]["text"] == "完整第一页内容"

    def test_same_page_deduplication(self, tmp_path):
        """同一页只返回一次"""
        vector_db_dir = tmp_path / "vector_dbs"
        vector_db_dir.mkdir(parents=True, exist_ok=True)
        documents_dir = tmp_path / "documents"
        documents_dir.mkdir(parents=True, exist_ok=True)
        bm25_db_dir = tmp_path / "bm25_dbs"
        bm25_db_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = tmp_path / "chunks_metadata.json"
        metadata_path.write_text("[]", encoding='utf-8')

        import faiss
        index = faiss.IndexFlatIP(1024)
        faiss.write_index(index, str(vector_db_dir / "all_docs.faiss"))

        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi([["dummy"]])
        with open(bm25_db_dir / "all_docs.pkl", 'wb') as f:
            pickle.dump(bm25, f)

        pages = [
            {"page": 1, "text": "完整第一页", "file_name": "test.md"},
        ]
        doc_data = {"metainfo": {"file_name": "test.md"}, "content": {"chunks": [], "pages": pages}}
        (documents_dir / "test.json").write_text(json.dumps(doc_data, ensure_ascii=False), encoding='utf-8')

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            retriever = MetadataFilteredRetriever(
                vector_db_dir=vector_db_dir,
                documents_dir=documents_dir,
                bm25_db_dir=bm25_db_dir,
                metadata_path=metadata_path,
                alpha=0.5
            )

        reranked = [
            {"page": 1, "file_name": "test.md", "text": "chunk1"},
            {"page": 1, "file_name": "test.md", "text": "chunk2"},
        ]
        result = retriever._replace_with_parent_pages(reranked)
        assert len(result) == 1


# ============================================================
# S-4.7 现状: VectorRetriever/BM25Retriever 分库模式不可用
# ============================================================

class TestPerCompanyRetrieversUnavailable:
    """锁定现状 S-4.7: 按公司名分库的检索器不可用"""

    def test_vector_retriever_expects_per_company_faiss(self, tmp_path):
        """
        现状: VectorRetriever 期望 {company_name}.faiss 格式索引，
        但 Ingestor 只生成 all_docs.faiss。
        使用 VectorRetriever 会因找不到文件而报错。
        """
        from src.retrieval import VectorRetriever

        vector_db_dir = tmp_path / "vector_dbs"
        vector_db_dir.mkdir(parents=True, exist_ok=True)
        documents_dir = tmp_path / "documents"
        documents_dir.mkdir(parents=True, exist_ok=True)

        import faiss
        index = faiss.IndexFlatIP(1024)
        faiss.write_index(index, str(vector_db_dir / "all_docs.faiss"))

        with patch.object(DashScopeEmbedding, '__init__', lambda self: None):
            with pytest.raises(Exception):
                retriever = VectorRetriever(vector_db_dir, documents_dir)
                retriever.retrieve_by_company_name("测试公司", "测试查询")

    def test_bm25_retriever_expects_per_company_pkl(self, tmp_path):
        """
        现状: BM25Retriever 期望 {company_name}.pkl 格式索引，
        但 Ingestor 只生成 all_docs.pkl。
        """
        from src.retrieval import BM25Retriever

        bm25_db_dir = tmp_path / "bm25_dbs"
        bm25_db_dir.mkdir(parents=True, exist_ok=True)
        documents_dir = tmp_path / "documents"
        documents_dir.mkdir(parents=True, exist_ok=True)

        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi([["dummy"]])
        with open(bm25_db_dir / "all_docs.pkl", 'wb') as f:
            pickle.dump(bm25, f)

        with pytest.raises(Exception):
            retriever = BM25Retriever(bm25_db_dir, documents_dir)
            retriever.retrieve_by_company_name("测试公司", "测试查询")


# ============================================================
# S-9 现状: DashScopeReranker 同名类覆盖
# ============================================================

class TestDashScopeRerankerOverride:
    """锁定现状 S-9: DashScopeReranker 第二个定义覆盖第一个"""

    def test_second_definition_is_active(self):
        """
        现状: reranking.py 中定义了两个 DashScopeReranker 类，
        第二个（原生 HTTP API）覆盖了第一个（OpenAI 兼容接口）。
        当前生效的是第二个定义。
        """
        from src.reranking import DashScopeReranker

        assert hasattr(DashScopeReranker, 'rerank')

        import inspect
        source = inspect.getsource(DashScopeReranker.rerank)
        assert "requests.post" in source or "dashscope.aliyuncs.com" in source, \
            "现状: 当前生效的 DashScopeReranker 应使用原生 HTTP API"
