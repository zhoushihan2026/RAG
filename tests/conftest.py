"""
RAG-cy 特征测试 - 公共 fixture

所有测试使用临时目录隔离，不读写真实数据库/缓存/配置。
"""
import os
import sys
import json
import shutil
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_dir(tmp_path):
    """提供干净的临时工作目录"""
    return tmp_path


@pytest.fixture
def tmp_dir_with_structure(tmp_path):
    """提供带有标准目录结构的临时目录"""
    dirs = {
        'root': tmp_path,
        'pdf_reports': tmp_path / 'pdf_reports',
        'debug_data': tmp_path / 'debug_data',
        'mineru_markdown': tmp_path / 'debug_data' / '01_mineru_markdown',
        'mineru_json': tmp_path / 'debug_data' / '01_mineru_json',
        'mineru_images': tmp_path / 'debug_data' / '01_mineru_images',
        'reports_markdown': tmp_path / 'debug_data' / '02_reports_markdown',
        'databases': tmp_path / 'databases',
        'vector_dbs': tmp_path / 'databases' / 'vector_dbs',
        'chunked_reports': tmp_path / 'databases' / 'chunked_reports',
        'bm25_dbs': tmp_path / 'databases' / 'bm25_dbs',
        'answers': tmp_path / 'answers',
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture
def sample_subset_csv(tmp_path):
    """生成示例 subset.csv"""
    csv_path = tmp_path / 'subset.csv'
    csv_content = "file_name,company_name,sha1,broker,doc_type,coverage_start,coverage_end\n"
    csv_content += "test_report,测试公司,stock_abc12,东方证券,券商研报,2024-01-01,2024-12-31\n"
    csv_content += "annual_report,测试公司,stock_def34,,年报,2024-01-01,2024-12-31\n"
    csv_content += "research_note,测试公司,stock_ghi56,,调研纪要,2024-06-01,2024-06-30\n"
    csv_path.write_text(csv_content, encoding='utf-8-sig')
    return csv_path


@pytest.fixture
def sample_content_list():
    """生成示例 content_list.json 数据"""
    return [
        {"type": "text", "text": "第一页标题", "page_idx": 0, "text_level": 1},
        {"type": "text", "text": "第一页正文内容", "page_idx": 0},
        {"type": "table", "table_body": "<table><tr><td>数据1</td></tr></table>",
         "table_caption": ["表1"], "page_idx": 0},
        {"type": "text", "text": "第二页标题", "page_idx": 1, "text_level": 1},
        {"type": "text", "text": "第二页正文内容", "page_idx": 1},
        {"type": "image", "img_path": "images/img_0_0.jpg", "page_idx": 1},
    ]


@pytest.fixture
def sample_markdown_text():
    """生成示例 markdown 文本（带页码标记）"""
    return """---

# Page 1

第一页标题

第一页正文内容

| 指标 | 数值 |
|------|------|
| 营收 | 100亿 |

---

# Page 2

第二页标题

第二页正文内容

![image](images/img_0_0.jpg)
"""


@pytest.fixture
def sample_chunks_metadata():
    """生成示例 chunks_metadata.json 数据"""
    return [
        {"company": "测试公司", "broker": "东方证券", "doc_type": "券商研报"},
        {"company": "测试公司", "broker": "东方证券", "doc_type": "券商研报"},
        {"company": "测试公司", "broker": "", "doc_type": "年报"},
        {"company": "其他公司", "broker": "", "doc_type": "年报"},
    ]


@pytest.fixture
def reset_global_singletons():
    """重置模块级单例/类变量，确保测试隔离"""
    from src.retrieval import VectorRetriever, DashScopeEmbedding
    # 保存原始值
    orig_model = VectorRetriever._model
    orig_client = DashScopeEmbedding._client
    # 重置
    VectorRetriever._model = None
    DashScopeEmbedding._client = None
    yield
    # 恢复
    VectorRetriever._model = orig_model
    DashScopeEmbedding._client = orig_client


@pytest.fixture
def reset_reranker_singleton():
    """重置 LocalReranker 单例"""
    from src.reranking import LocalReranker
    orig_model = LocalReranker._model
    orig_available = LocalReranker._model_available
    LocalReranker._model = None
    LocalReranker._model_available = None
    yield
    LocalReranker._model = orig_model
    LocalReranker._model_available = orig_available


@pytest.fixture
def mock_env_vars(monkeypatch):
    """提供模拟的环境变量，避免真实 API 调用"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-fake-key-12345")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-12345")
    monkeypatch.setenv("MINERU_API_KEY", "test-mineru-key")
