"""
v2 API 路由测试
锁定 v2-spec 中定义的会话管理 API 行为：
- POST /api/chat（含 session_id 和历史消息）
- GET /api/sessions
- GET /api/sessions/{id}
- DELETE /api/sessions/{id}
- PATCH /api/sessions/{id}
- 会话上限校验
- CORS 更新（DELETE, PATCH）
"""
import pytest
import json
from unittest.mock import patch, MagicMock


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_pipeline():
    """创建 mock Pipeline 实例"""
    with patch("src.pipeline.Pipeline.__init__", return_value=None):
        from src.pipeline import Pipeline, RunConfig
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.run_config = RunConfig()
        pipeline.paths = MagicMock()
        yield pipeline


@pytest.fixture
def v2_app_client(mock_pipeline):
    """创建 v2 FastAPI TestClient，注入 mock Pipeline 和 SessionManager"""
    with patch("src.pipeline.Pipeline", return_value=mock_pipeline):
        from api.app import create_app
        app = create_app(pipeline=mock_pipeline)
        from fastapi.testclient import TestClient
        client = TestClient(app)
        yield client, mock_pipeline, app.state.session_manager


# ============================================================
# POST /api/chat v2 行为
# ============================================================

class TestChatV2:
    """锁定 v2-spec 3.1: POST /api/chat 含 session_id"""

    def test_chat_with_session_id_saves_user_message(self, v2_app_client):
        """带 session_id 的请求将用户问题保存到会话"""
        client, pipeline, sm = v2_app_client

        def mock_stream(question, kind="string", history_messages=None):
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
            json={"question": "测试问题", "session_id": "sid-001"},
        )
        assert response.status_code == 200

        # 验证用户消息被保存
        detail = sm.get_session_detail("sid-001")
        assert detail is not None
        user_msgs = [m for m in detail["messages"] if m["role"] == "user"]
        assert len(user_msgs) >= 1
        assert user_msgs[0]["content"] == "测试问题"

    def test_chat_with_session_id_saves_assistant_answer(self, v2_app_client):
        """回答完成后将助手答案保存到会话"""
        client, pipeline, sm = v2_app_client

        def mock_stream(question, kind="string", history_messages=None):
            yield {"type": "done", "content": {
                "final_answer": "2024年营收577.96亿元",
                "step_by_step_analysis": "推理过程",
                "reasoning_summary": "摘要",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "中芯国际营收", "session_id": "sid-001"},
        )
        assert response.status_code == 200

        detail = sm.get_session_detail("sid-001")
        assistant_msgs = [m for m in detail["messages"] if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        assert "577.96" in assistant_msgs[0]["content"]

    def test_chat_passes_history_to_pipeline(self, v2_app_client):
        """第二次提问时，Pipeline 收到历史消息"""
        client, pipeline, sm = v2_app_client

        received_history = []

        def mock_stream(question, kind="string", history_messages=None):
            received_history.append(history_messages)
            yield {"type": "done", "content": {
                "final_answer": "答案",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        # 第一次提问
        client.post("/api/chat", json={"question": "问题1", "session_id": "sid-001"})
        # 第二次提问
        client.post("/api/chat", json={"question": "问题2", "session_id": "sid-001"})

        # 第二次调用应传入历史消息
        assert len(received_history) == 2
        assert received_history[0] is None or received_history[0] == []
        assert received_history[1] is not None and len(received_history[1]) > 0

    def test_chat_final_answer_fallback_to_analysis(self, v2_app_client):
        """v2: final_answer 为空时回退使用 step_by_step_analysis"""
        client, pipeline, sm = v2_app_client

        def mock_stream(question, kind="string", history_messages=None):
            yield {"type": "done", "content": {
                "final_answer": "",
                "step_by_step_analysis": "推理过程内容",
                "reasoning_summary": "摘要",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        response = client.post(
            "/api/chat",
            json={"question": "测试问题", "session_id": "sid-001"},
        )
        assert response.status_code == 200

        detail = sm.get_session_detail("sid-001")
        assistant_msgs = [m for m in detail["messages"] if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        # final_answer 为空时，应回退使用 step_by_step_analysis
        assert "推理过程内容" in assistant_msgs[0]["content"]

    def test_chat_no_session_id_auto_generates(self, v2_app_client):
        """v1 兼容: 不传 session_id 时自动生成"""
        client, pipeline, sm = v2_app_client

        def mock_stream(question, kind="string", history_messages=None):
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

    def test_chat_session_limit_returns_error(self, v2_app_client):
        """会话达到 50 条用户消息上限时返回 error 事件"""
        client, pipeline, sm = v2_app_client

        # 预填充 50 条用户消息
        for i in range(50):
            sm.add_message("sid-001", "user", f"问题{i+1}")
            sm.add_message("sid-001", "assistant", f"答案{i+1}")

        response = client.post(
            "/api/chat",
            json={"question": "第51个问题", "session_id": "sid-001"},
        )
        assert response.status_code == 200
        text = response.text
        assert "error" in text
        assert "上限" in text or "50" in text


# ============================================================
# GET /api/sessions
# ============================================================

class TestListSessions:
    """锁定 v2-spec 3.2: GET /api/sessions"""

    def test_list_sessions_empty(self, v2_app_client):
        """无会话时返回空列表"""
        client, _, _ = v2_app_client
        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []

    def test_list_sessions_after_chat(self, v2_app_client):
        """提问后会话列表包含新会话"""
        client, pipeline, _ = v2_app_client

        def mock_stream(question, kind="string", history_messages=None):
            yield {"type": "done", "content": {
                "final_answer": "答案",
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "source_files": {},
                "references": []
            }}

        pipeline.answer_single_question_stream = mock_stream

        client.post("/api/chat", json={"question": "测试问题", "session_id": "sid-001"})

        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "sid-001"

    def test_list_sessions_sorted_by_time(self, v2_app_client):
        """会话列表按时间倒序"""
        client, _, sm = v2_app_client
        sm.add_message("sid-001", "user", "第一个问题")
        sm.add_message("sid-002", "user", "第二个问题")

        response = client.get("/api/sessions")
        data = response.json()
        assert data["sessions"][0]["id"] == "sid-002"


# ============================================================
# GET /api/sessions/{id}
# ============================================================

class TestGetSession:
    """锁定 v2-spec 3.3: GET /api/sessions/{id}"""

    def test_get_session_exists(self, v2_app_client):
        """存在的会话返回详情"""
        client, _, sm = v2_app_client
        sm.add_message("sid-001", "user", "测试问题")
        sm.add_message("sid-001", "assistant", "测试答案")

        response = client.get("/api/sessions/sid-001")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "sid-001"
        assert len(data["messages"]) == 2

    def test_get_session_not_exists(self, v2_app_client):
        """不存在的会话返回 404"""
        client, _, _ = v2_app_client
        response = client.get("/api/sessions/nonexistent")
        assert response.status_code == 404


# ============================================================
# DELETE /api/sessions/{id}
# ============================================================

class TestDeleteSession:
    """锁定 v2-spec 3.4: DELETE /api/sessions/{id}"""

    def test_delete_session(self, v2_app_client):
        """删除会话后返回 deleted 状态"""
        client, _, sm = v2_app_client
        sm.add_message("sid-001", "user", "问题")

        response = client.delete("/api/sessions/sid-001")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

    def test_delete_session_then_get_404(self, v2_app_client):
        """删除后再获取返回 404"""
        client, _, sm = v2_app_client
        sm.add_message("sid-001", "user", "问题")

        client.delete("/api/sessions/sid-001")
        response = client.get("/api/sessions/sid-001")
        assert response.status_code == 404

    def test_delete_nonexistent_session(self, v2_app_client):
        """删除不存在的会话也返回成功（幂等）"""
        client, _, _ = v2_app_client
        response = client.delete("/api/sessions/nonexistent")
        assert response.status_code == 200


# ============================================================
# PATCH /api/sessions/{id}
# ============================================================

class TestRenameSession:
    """锁定 v2-spec 3.5: PATCH /api/sessions/{id}"""

    def test_rename_session(self, v2_app_client):
        """重命名会话标题"""
        client, _, sm = v2_app_client
        sm.add_message("sid-001", "user", "问题")

        response = client.patch(
            "/api/sessions/sid-001",
            json={"title": "新标题"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "新标题"

    def test_rename_nonexistent_session_404(self, v2_app_client):
        """重命名不存在的会话返回 404"""
        client, _, _ = v2_app_client
        response = client.patch(
            "/api/sessions/nonexistent",
            json={"title": "新标题"},
        )
        assert response.status_code == 404


# ============================================================
# CORS 更新
# ============================================================

class TestCORSUpdateV2:
    """锁定 v2-spec 9.10: CORS 允许 DELETE 和 PATCH"""

    def test_cors_allows_delete(self, v2_app_client):
        """CORS 允许 DELETE 方法"""
        client, _, _ = v2_app_client
        response = client.options(
            "/api/sessions/sid-001",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "DELETE",
            },
        )
        assert response.status_code == 200
        allowed = response.headers.get("access-control-allow-methods", "")
        assert "DELETE" in allowed

    def test_cors_allows_patch(self, v2_app_client):
        """CORS 允许 PATCH 方法"""
        client, _, _ = v2_app_client
        response = client.options(
            "/api/sessions/sid-001",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        assert response.status_code == 200
        allowed = response.headers.get("access-control-allow-methods", "")
        assert "PATCH" in allowed
