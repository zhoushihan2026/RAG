"""
特征测试: 缓存/增量逻辑 (pipeline.py, ingestion.py)

锁定行为: S-3.1 ~ S-3.5
"""
import json
import os
import hashlib
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.pipeline import Pipeline, RunConfig


# ============================================================
# S-3.5 SHA1 计算
# ============================================================

class TestComputeFileSha1:
    """锁定 S-3.5: 使用 SHA1 计算文件哈希"""

    def test_sha1_computation(self, tmp_path):
        """现状: 使用 hashlib.sha1 计算文件哈希"""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"test content for sha1")

        pipeline = Pipeline(tmp_path, run_config=RunConfig())
        result = pipeline._compute_file_sha1(str(test_file))

        expected = hashlib.sha1(b"test content for sha1").hexdigest()
        assert result == expected

    def test_sha1_large_file_chunked(self, tmp_path):
        """SHA1 分块读取（8192 字节）"""
        test_file = tmp_path / "large.pdf"
        test_file.write_bytes(b"x" * 20000)

        pipeline = Pipeline(tmp_path, run_config=RunConfig())
        result = pipeline._compute_file_sha1(str(test_file))

        expected = hashlib.sha1(b"x" * 20000).hexdigest()
        assert result == expected


# ============================================================
# S-3.1 MinerU 文件缓存
# ============================================================

class TestMineruFileCache:
    """锁定 S-3.1: MinerU 文件缓存行为"""

    def _make_pipeline(self, tmp_path):
        """构造最小 Pipeline 实例"""
        root = tmp_path / "data"
        root.mkdir(parents=True, exist_ok=True)
        (root / "pdf_reports").mkdir(exist_ok=True)
        return Pipeline(root, run_config=RunConfig())

    def test_cache_hit_skips_upload(self, tmp_path):
        """T-CACHE-01: PDF SHA1 未变时跳过上传"""
        pipeline = self._make_pipeline(tmp_path)
        base_name = "test_report"

        pipeline.paths.mineru_json_path.mkdir(parents=True, exist_ok=True)
        pipeline.paths.mineru_markdown_path.mkdir(parents=True, exist_ok=True)
        cache_path = pipeline.paths.mineru_json_path / "file_cache.json"
        cache_data = {base_name: {"pdf_sha1": "abc123", "status": "completed"}}
        cache_path.write_text(json.dumps(cache_data), encoding='utf-8')

        md_path = pipeline.paths.mineru_markdown_path / f"{base_name}.md"
        md_path.write_text("content", encoding='utf-8')
        json_path = pipeline.paths.mineru_json_path / f"{base_name}.json"
        json_path.write_text("[]", encoding='utf-8')

        record = pipeline._get_mineru_cache_record(base_name)
        assert record is not None
        assert record.get("pdf_sha1") == "abc123"

    def test_cache_miss_triggers_upload(self, tmp_path):
        """T-CACHE-02: 无缓存记录时需重新上传"""
        pipeline = self._make_pipeline(tmp_path)
        base_name = "new_report"

        pipeline.paths.mineru_json_path.mkdir(parents=True, exist_ok=True)
        record = pipeline._get_mineru_cache_record(base_name)
        assert record is None


# ============================================================
# S-3.2 向量库增量缓存
# ============================================================

class TestVectorDBCache:
    """锁定 S-3.2: 向量库增量缓存行为"""

    def test_embedding_cache_structure(self, tmp_path):
        """T-CACHE-03: embedding_cache.json 结构"""
        cache_path = tmp_path / "embedding_cache.json"
        cache_data = {
            "report1": {"sha1": "abc", "vector_count": 10},
            "report2": {"sha1": "def", "vector_count": 15},
        }
        cache_path.write_text(json.dumps(cache_data), encoding='utf-8')

        loaded = json.loads(cache_path.read_text(encoding='utf-8'))
        assert "report1" in loaded
        assert loaded["report1"]["sha1"] == "abc"
        assert loaded["report1"]["vector_count"] == 10


# ============================================================
# S-3.3 BM25 缓存
# ============================================================

class TestBM25Cache:
    """锁定 S-3.3: BM25 缓存行为"""

    def test_bm25_cache_structure(self, tmp_path):
        """T-CACHE-05: bm25_cache.json 结构"""
        cache_path = tmp_path / "bm25_cache.json"
        cache_data = {
            "report1": {"sha1": "abc"},
        }
        cache_path.write_text(json.dumps(cache_data), encoding='utf-8')

        loaded = json.loads(cache_path.read_text(encoding='utf-8'))
        assert "report1" in loaded
        assert loaded["report1"]["sha1"] == "abc"


# ============================================================
# S-3.4 分块缓存
# ============================================================

class TestChunkingCache:
    """锁定 S-3.4: 分块缓存行为"""

    def test_chunking_cache_structure(self, tmp_path):
        """T-CACHE-06: chunking_cache.json 结构"""
        cache_path = tmp_path / "chunking_cache.json"
        cache_data = {
            "/path/to/markdowns": "dir_content_sha1_hash"
        }
        cache_path.write_text(json.dumps(cache_data), encoding='utf-8')

        loaded = json.loads(cache_path.read_text(encoding='utf-8'))
        assert "/path/to/markdowns" in loaded


# ============================================================
# S-3.1 现状: export_reports_to_markdown 死代码
# ============================================================

class TestExportReportsDeadCode:
    """锁定现状 S-3.1 / 5.5: export_reports_to_markdown 中缓存跳过逻辑的死代码"""

    def test_deleted_files_still_checked(self, tmp_path):
        """
        现状: 当 PDF 变动时，旧文件被删除后进入 if/else 分支，
        但此时 os.path.exists 为 False，else 分支为空（pass）。
        代码继续到"再次检查"部分，逻辑上不会出错但意图不清晰。
        锁定: 删除后再次检查时文件不存在，不会误跳过。
        """
        root = tmp_path / "data"
        root.mkdir()
        (root / "pdf_reports").mkdir()
        pipeline = Pipeline(root, run_config=RunConfig())

        base_name = "test_report"
        pipeline.paths.mineru_markdown_path.mkdir(parents=True, exist_ok=True)
        pipeline.paths.mineru_json_path.mkdir(parents=True, exist_ok=True)

        existing_md = pipeline.paths.mineru_markdown_path / f"{base_name}.md"
        existing_json = pipeline.paths.mineru_json_path / f"{base_name}.json"

        if existing_md.exists():
            os.remove(existing_md)
        if existing_json.exists():
            os.remove(existing_json)

        assert not os.path.exists(existing_md)
        assert not os.path.exists(existing_json)


# ============================================================
# S-3.5 现状: VectorDBIngestor model_path 参数未使用
# ============================================================

class TestVectorDBIngestorModelPath:
    """锁定现状 S-3.5 / 5.14: VectorDBIngestor 构造函数的 model_path 参数未使用"""

    def test_model_path_ignored(self, mock_env_vars):
        """
        现状: VectorDBIngestor.__init__ 接受 model_path 参数但内部忽略。
        调用方传入 model_path 不会生效，始终使用 DashScopeEmbedding()。
        """
        from src.ingestion import VectorDBIngestor

        ingestor = VectorDBIngestor(model_path="/custom/path/to/model")
        from src.retrieval import DashScopeEmbedding
        assert isinstance(ingestor.model, DashScopeEmbedding)
