"""
FastAPI 接口测试
锁定 API 契约 spec 中定义的所有接口行为
使用 TestClient 进行集成测试，mock Pipeline 层避免真实 API 调用
"""
import pytest
import json
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_pipeline():
    """创建 mock Pipeline 实例，避免初始化时访问文件系统"""
    with patch("src.pipeline.Pipeline.__init__", return_value=None):
        from src.pipeline import Pipeline, RunConfig
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.run_config = RunConfig()
        pipeline.paths = MagicMock()
        yield pipeline


@pytest.fixture
def app_client(mock_pipeline):
    """创建 FastAPI TestClient，注入 mock Pipeline"""
    with patch("src.pipeline.Pipeline", return_value=mock_pipeline):
        # 延迟导入，确保 mock 生效
        from api.app import create_app
        app = create_app(pipeline=mock_pipeline)
        from fastapi.testclient import TestClient
        client = TestClient(app)
        yield client


@pytest.fixture
def app_client_with_pipeline():
    """
    创建 FastAPI TestClient，使用可自定义的 mock Pipeline。
    返回 (client, pipeline) 元组，允许测试自定义 Pipeline 行为。
    """
    with patch("src.pipeline.Pipeline.__init__", return_value=None):
        from src.pipeline import Pipeline, RunConfig
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.run_config = RunConfig()
        pipeline.paths = MagicMock()

        with patch("src.pipeline.Pipeline", return_value=pipeline):
            from api.app import create_app
            app = create_app(pipeline=pipeline)
            from fastapi.testclient import TestClient
            client = TestClient(app)
            yield client, pipeline


# ============================================================
# 健康检查
# ============================================================

class TestHealthEndpoint:
    """锁定 API-Spec 4: GET /api/health"""

    def test_health_returns_ok(self, app_client):
        """健康检查返回 status: ok"""
        response = app_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


# ============================================================
# 问答接口
# ============================================================

class TestChatEndpoint:
    """锁定 API-Spec 1: POST /api/chat"""

    def test_chat_empty_question_returns_422(self, app_client):
        """空问题返回 422 (FastAPI Pydantic min_length 验证)"""
        response = app_client.post(
            "/api/chat",
            json={"question": ""},
        )
        assert response.status_code == 422

    def test_chat_missing_question_returns_422(self, app_client):
        """缺少 question 字段返回 422 (FastAPI 验证)"""
        response = app_client.post(
            "/api/chat",
            json={},
        )
        assert response.status_code == 422

    def test_chat_with_session_id_accepted(self, app_client_with_pipeline):
        """v1 行为: session_id 被接受但忽略，不报错"""
        client, pipeline = app_client_with_pipeline

        # mock 流式生成器
        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "正在初始化..."}
            yield {"type": "done", "content": {
                "final_answer": "测试答案",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "测试问题", "session_id": "test-session-123"},
        )
        # v1: session_id 不报错，正常处理
        assert response.status_code == 200

    def test_chat_sse_status_events(self, app_client_with_pipeline):
        """SSE 流中包含 status 事件"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "正在识别公司名称..."}
            yield {"type": "status", "content": "正在检索相关文档..."}
            yield {"type": "done", "content": {
                "final_answer": "答案",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "中芯国际2024年营收"},
        )
        assert response.status_code == 200
        # 验证 SSE 内容中包含 status 事件
        text = response.text
        assert "status" in text
        assert "正在识别公司名称" in text

    def test_chat_sse_token_events(self, app_client_with_pipeline):
        """SSE 流中包含 token 事件（流式输出）"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "正在生成回答..."}
            yield {"type": "stream_start", "content": ""}
            yield {"type": "token", "content": "2024"}
            yield {"type": "token", "content": "年营收"}
            yield {"type": "done", "content": {
                "final_answer": "2024年营收577.96亿元",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [5],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "中芯国际2024年营收"},
        )
        assert response.status_code == 200
        text = response.text
        assert "token" in text
        assert "2024" in text

    def test_chat_sse_done_event_structure(self, app_client_with_pipeline):
        """done 事件的 content 包含完整答案结构"""
        client, pipeline = app_client_with_pipeline

        expected_answer = {
            "final_answer": "2024年研发投入占比约11.4%",
            "step_by_step_analysis": "1. 从年报提取数据...",
            "reasoning_summary": "直接从年报提取",
            "relevant_pages": [5, 8],
            "source_files": {
                "abc123": {"file_name": "中芯国际2024年年度报告", "company_name": "中芯国际"}
            },
            "references": [
                {"pdf_sha1": "abc123", "page_index": 5, "source_file": "中芯国际2024年年度报告"}
            ]
        }

        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "正在生成回答..."}
            yield {"type": "stream_start", "content": ""}
            yield {"type": "done", "content": expected_answer}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "中芯国际2024年研发投入占比"},
        )
        assert response.status_code == 200
        text = response.text
        # 验证 done 事件中包含完整结构
        assert "done" in text
        assert "final_answer" in text
        assert "step_by_step_analysis" in text
        assert "relevant_pages" in text
        assert "source_files" in text
        assert "references" in text

    def test_chat_error_event(self, app_client_with_pipeline):
        """SSE 流中包含 error 事件"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "error", "content": "未在问题中找到公司名称"}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "随便一个问题没有公司名"},
        )
        assert response.status_code == 200
        text = response.text
        assert "error" in text
        assert "未在问题中找到公司名称" in text

    def test_chat_pipeline_exception_returns_error_event(self, app_client_with_pipeline):
        """Pipeline 内部异常在 SSE 流中返回 error 事件"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            raise RuntimeError("Pipeline 内部错误")

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "测试问题"},
        )
        # SSE 流始终返回 200，异常在 error 事件中传递
        assert response.status_code == 200
        text = response.text
        assert "error" in text


# ============================================================
# 文件上传接口
# ============================================================

class TestUploadEndpoint:
    """锁定 API-Spec 2: POST /api/upload"""

    def test_upload_no_file_returns_422(self, app_client_with_pipeline):
        """未提供文件返回 422 (FastAPI File 必填验证)"""
        client, _ = app_client_with_pipeline
        response = client.post("/api/upload")
        assert response.status_code == 422

    def test_upload_non_pdf_returns_400(self, app_client_with_pipeline):
        """非 PDF 文件返回 400"""
        client, pipeline = app_client_with_pipeline

        import io
        fake_file = io.BytesIO(b"not a pdf")
        response = client.post(
            "/api/upload",
            files={"file": ("test.txt", fake_file, "text/plain")},
        )
        assert response.status_code == 400

    def test_upload_success(self, app_client_with_pipeline):
        """上传成功返回 success 状态"""
        client, pipeline = app_client_with_pipeline

        pipeline.process_single_pdf_file = MagicMock(return_value={
            "status": "success",
            "message": "上传数据库成功",
            "file_name": "测试报告"
        })

        import io
        fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")
        response = client.post(
            "/api/upload",
            files={"file": ("测试报告.pdf", fake_pdf, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["file_name"] == "测试报告"

    def test_upload_existing_file(self, app_client_with_pipeline):
        """文件已存在返回 exists 状态"""
        client, pipeline = app_client_with_pipeline

        pipeline.process_single_pdf_file = MagicMock(return_value={
            "status": "exists",
            "message": "该文件已在数据库中",
            "file_name": "已有报告"
        })

        import io
        fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")
        response = client.post(
            "/api/upload",
            files={"file": ("已有报告.pdf", fake_pdf, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "exists"

    def test_upload_processing_error(self, app_client_with_pipeline):
        """处理失败返回 error 状态"""
        client, pipeline = app_client_with_pipeline

        pipeline.process_single_pdf_file = MagicMock(return_value={
            "status": "error",
            "message": "处理失败: 文件损坏",
            "file_name": "损坏文件"
        })

        import io
        fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")
        response = client.post(
            "/api/upload",
            files={"file": ("损坏文件.pdf", fake_pdf, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"


# ============================================================
# 知识库状态接口
# ============================================================

class TestKBStatusEndpoint:
    """锁定 API-Spec 3: GET /api/kb/status"""

    def test_kb_status_returns_file_list(self, app_client_with_pipeline):
        """返回知识库文件列表"""
        client, pipeline = app_client_with_pipeline

        pipeline._get_source_file_names = MagicMock(return_value={
            "abc123": {"file_name": "中芯国际2024年年度报告", "company_name": "中芯国际"},
            "def456": {"file_name": "东方证券研报", "company_name": "中芯国际"},
        })

        response = client.get("/api/kb/status")
        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 2
        assert len(data["files"]) == 2
        # 验证文件结构
        for f in data["files"]:
            assert "sha1" in f
            assert "file_name" in f
            assert "company_name" in f

    def test_kb_status_empty(self, app_client_with_pipeline):
        """空知识库返回 total_files=0"""
        client, pipeline = app_client_with_pipeline

        pipeline._get_source_file_names = MagicMock(return_value={})

        response = client.get("/api/kb/status")
        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 0
        assert data["files"] == []


# ============================================================
# CORS 配置
# ============================================================

class TestCORSConfiguration:
    """锁定 API-Spec 8: CORS 配置"""

    def test_cors_headers_present(self, app_client):
        """OPTIONS 请求返回 CORS 头"""
        response = app_client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_cors_allows_post(self, app_client):
        """CORS 允许 POST 方法"""
        response = app_client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert response.status_code == 200
        allowed_methods = response.headers.get("access-control-allow-methods", "")
        assert "POST" in allowed_methods

    def test_cors_127_origin_allowed(self, app_client):
        """127.0.0.1 来源也被 CORS 允许"""
        response = app_client.options(
            "/api/health",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"

    def test_cors_unknown_origin_rejected(self, app_client):
        """未知来源不被 CORS 允许"""
        response = app_client.options(
            "/api/health",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") is None


# ============================================================
# SSE 格式验证
# ============================================================

class TestSSEFormat:
    """锁定 SSE 事件流格式规范"""

    def test_sse_event_format(self, app_client_with_pipeline):
        """每个 SSE 事件由 event: 和 data: 行组成，以空行结束"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "正在初始化..."}
            yield {"type": "done", "content": {
                "final_answer": "答案",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "测试问题"},
        )
        assert response.status_code == 200
        text = response.text
        # 验证 SSE 格式: event: xxx\ndata: xxx\n\n
        assert "event: status\ndata: 正在初始化...\n\n" in text
        assert "event: done\ndata: " in text

    def test_sse_stream_start_event(self, app_client_with_pipeline):
        """stream_start 事件正确输出"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "正在生成回答..."}
            yield {"type": "stream_start", "content": ""}
            yield {"type": "token", "content": "你好"}
            yield {"type": "done", "content": {
                "final_answer": "你好",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "你好"},
        )
        text = response.text
        assert "event: stream_start" in text
        # stream_start 的 data 为空字符串
        assert "event: stream_start\ndata: \n\n" in text

    def test_sse_status_events_in_order(self, app_client_with_pipeline):
        """多个 status 事件按顺序输出"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "步骤1"}
            yield {"type": "status", "content": "步骤2"}
            yield {"type": "status", "content": "步骤3"}
            yield {"type": "done", "content": {
                "final_answer": "答案",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "测试"},
        )
        text = response.text
        # 验证顺序: 步骤1 在步骤2 之前
        pos1 = text.index("步骤1")
        pos2 = text.index("步骤2")
        pos3 = text.index("步骤3")
        assert pos1 < pos2 < pos3

    def test_sse_error_stops_stream(self, app_client_with_pipeline):
        """error 事件后不再有后续事件"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "正在识别公司名称..."}
            yield {"type": "error", "content": "未在问题中找到公司名称"}
            return  # error 后直接返回

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "没有公司名的问题"},
        )
        text = response.text
        # error 事件后不应有 done 事件
        assert "error" in text
        assert "未在问题中找到公司名称" in text
        assert "done" not in text

    def test_sse_done_content_is_valid_json(self, app_client_with_pipeline):
        """done 事件的 data 是合法 JSON"""
        client, pipeline = app_client_with_pipeline

        expected = {
            "final_answer": "测试答案",
            "step_by_step_analysis": "推理过程",
            "reasoning_summary": "摘要",
            "relevant_pages": [1, 2, 3],
            "source_files": {"sha1abc": {"file_name": "报告.pdf", "company_name": "测试公司"}},
            "references": [{"pdf_sha1": "sha1abc", "page_index": 1, "source_file": "报告.pdf"}]
        }

        def mock_stream(question, kind="string"):
            yield {"type": "done", "content": expected}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "测试"},
        )
        text = response.text
        # 提取 done 事件的 data
        for line in text.split("\n"):
            if line.startswith("data: ") and "final_answer" in line:
                data_str = line[6:]
                parsed = json.loads(data_str)
                assert parsed["final_answer"] == "测试答案"
                assert parsed["relevant_pages"] == [1, 2, 3]
                assert "sha1abc" in parsed["source_files"]
                assert len(parsed["references"]) == 1
                break


# ============================================================
# 问答边界场景
# ============================================================

class TestChatEdgeCases:
    """问答接口边界场景"""

    def test_chat_whitespace_only_question_accepted(self, app_client_with_pipeline):
        """仅含空格的问题也能通过 Pydantic 验证（min_length 不 strip）"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "done", "content": {
                "final_answer": "答案",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "   "},
        )
        # Pydantic min_length=1 不 strip 空格，"   " 长度为 3，通过验证
        assert response.status_code == 200

    def test_chat_very_long_question_accepted(self, app_client_with_pipeline):
        """超长问题也能被接受（不限制最大长度）"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "done", "content": {
                "final_answer": "答案",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        long_question = "中芯国际" + "的营收" * 500
        response = client.post(
            "/api/chat",
            json={"question": long_question},
        )
        assert response.status_code == 200

    def test_chat_special_characters_in_question(self, app_client_with_pipeline):
        """问题中包含特殊字符也能正常处理"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "done", "content": {
                "final_answer": "答案",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "中芯国际<>&\"'2024年营收"},
        )
        assert response.status_code == 200

    def test_chat_no_company_error_message(self, app_client_with_pipeline):
        """未找到公司名时返回明确的错误消息"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "正在识别公司名称..."}
            yield {"type": "error", "content": "未在问题中找到公司名称"}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "今天天气怎么样"},
        )
        assert response.status_code == 200
        text = response.text
        assert "未在问题中找到公司名称" in text

    def test_chat_no_retrieval_results_error(self, app_client_with_pipeline):
        """检索无结果时返回明确的错误消息"""
        client, pipeline = app_client_with_pipeline

        def mock_stream(question, kind="string"):
            yield {"type": "status", "content": "正在识别公司名称..."}
            yield {"type": "status", "content": "正在检索 中芯国际 的相关文档..."}
            yield {"type": "error", "content": "未找到相关文档"}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "中芯国际2099年营收"},
        )
        assert response.status_code == 200
        text = response.text
        assert "未找到相关文档" in text


# ============================================================
# 上传边界场景
# ============================================================

class TestUploadEdgeCases:
    """上传接口边界场景"""

    def test_upload_empty_pdf(self, app_client_with_pipeline):
        """空 PDF 文件也能上传（由 Pipeline 处理）"""
        client, pipeline = app_client_with_pipeline

        pipeline.process_single_pdf_file = MagicMock(return_value={
            "status": "error",
            "message": "PDF 文件为空或无法解析",
            "file_name": "empty.pdf"
        })

        import io
        empty_pdf = io.BytesIO(b"")
        response = client.post(
            "/api/upload",
            files={"file": ("empty.pdf", empty_pdf, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"

    def test_upload_long_filename(self, app_client_with_pipeline):
        """长文件名也能正常处理"""
        client, pipeline = app_client_with_pipeline

        pipeline.process_single_pdf_file = MagicMock(return_value={
            "status": "success",
            "message": "上传成功",
            "file_name": "很长的文件名" * 20
        })

        import io
        fake_pdf = io.BytesIO(b"%PDF-1.4 fake")
        long_name = "很长的文件名" * 20 + ".pdf"
        response = client.post(
            "/api/upload",
            files={"file": (long_name, fake_pdf, "application/pdf")},
        )
        assert response.status_code == 200

    def test_upload_pipeline_exception_returns_500(self, app_client_with_pipeline):
        """Pipeline 处理异常返回 500"""
        client, pipeline = app_client_with_pipeline

        pipeline.process_single_pdf_file = MagicMock(
            side_effect=RuntimeError("处理失败")
        )

        import io
        fake_pdf = io.BytesIO(b"%PDF-1.4 fake")
        response = client.post(
            "/api/upload",
            files={"file": ("test.pdf", fake_pdf, "application/pdf")},
        )
        assert response.status_code == 500


# ============================================================
# 知识库状态边界场景
# ============================================================

class TestKBStatusEdgeCases:
    """知识库状态接口边界场景"""

    def test_kb_status_file_with_missing_fields(self, app_client_with_pipeline):
        """文件信息缺少字段时仍能返回"""
        client, pipeline = app_client_with_pipeline

        # 模拟缺少 company_name 的情况
        pipeline._get_source_file_names = MagicMock(return_value={
            "abc123": {"file_name": "测试报告"},
        })

        response = client.get("/api/kb/status")
        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 1
        # company_name 缺失时应为空字符串
        assert data["files"][0]["company_name"] == ""

    def test_kb_status_response_structure(self, app_client_with_pipeline):
        """响应结构严格匹配 KBStatusResponse"""
        client, pipeline = app_client_with_pipeline

        pipeline._get_source_file_names = MagicMock(return_value={
            "sha1": {"file_name": "报告.pdf", "company_name": "公司A"},
        })

        response = client.get("/api/kb/status")
        data = response.json()
        # 顶层字段
        assert "total_files" in data
        assert "files" in data
        # files 数组中每个元素的字段
        f = data["files"][0]
        assert set(f.keys()) == {"sha1", "file_name", "company_name"}
