"""
SessionManager 单元测试
锁定 v2-spec 中定义的会话管理行为：
- 会话创建与获取
- 消息添加与标题自动设置
- 历史消息截断策略
- 会话列表排序
- 会话删除与重命名
- 过期清理
- 消息上限校验
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def session_manager():
    """创建干净的 SessionManager 实例"""
    from src.session_manager import SessionManager
    return SessionManager(max_user_messages_per_session=50, max_history_rounds=5)


@pytest.fixture
def populated_manager(session_manager):
    """创建包含多轮对话的 SessionManager"""
    sid = "test-session-001"
    session_manager.add_message(sid, "user", "中芯国际2024年研发投入占营业收入的比例是多少？")
    session_manager.add_message(sid, "assistant", "2024年研发投入占营业收入比例约11.4%")
    session_manager.add_message(sid, "user", "它的营收呢？")
    session_manager.add_message(sid, "assistant", "2024年营收577.96亿元")
    return session_manager, sid


# ============================================================
# 会话创建与获取
# ============================================================

class TestSessionCreation:
    """锁定 v2-spec 4.1: SessionManager.get_or_create"""

    def test_get_or_create_new_session(self, session_manager):
        """新 session_id 自动创建会话"""
        session = session_manager.get_or_create("new-id-001")
        assert session is not None
        assert session.session_id == "new-id-001"
        assert session.title == "新对话"
        assert len(session.messages) == 0

    def test_get_or_create_existing_session(self, session_manager):
        """已存在的 session_id 返回同一会话"""
        s1 = session_manager.get_or_create("id-001")
        s2 = session_manager.get_or_create("id-001")
        assert s1 is s2

    def test_different_session_ids_create_different_sessions(self, session_manager):
        """不同 session_id 创建不同会话"""
        s1 = session_manager.get_or_create("id-001")
        s2 = session_manager.get_or_create("id-002")
        assert s1 is not s2


# ============================================================
# 消息添加与标题自动设置
# ============================================================

class TestMessageAddition:
    """锁定 v2-spec 4.1: Session.add_message / SessionManager.add_message"""

    def test_add_user_message(self, session_manager):
        """添加用户消息"""
        session_manager.add_message("sid-001", "user", "测试问题")
        session = session_manager.get_or_create("sid-001")
        assert len(session.messages) == 1
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "测试问题"

    def test_add_assistant_message(self, session_manager):
        """添加助手消息"""
        session_manager.add_message("sid-001", "user", "测试问题")
        session_manager.add_message("sid-001", "assistant", "测试答案")
        session = session_manager.get_or_create("sid-001")
        assert len(session.messages) == 2
        assert session.messages[1].role == "assistant"
        assert session.messages[1].content == "测试答案"

    def test_first_user_message_sets_title(self, session_manager):
        """首条用户消息自动设置会话标题（前20字）"""
        session_manager.add_message("sid-001", "user", "中芯国际2024年研发投入占营业收入的比例是多少？")
        session = session_manager.get_or_create("sid-001")
        assert session.title == "中芯国际2024年研发投入占营业收入的比例是多少？"[:20]

    def test_title_not_overwritten_by_later_messages(self, session_manager):
        """标题只在首条用户消息时设置，后续消息不覆盖"""
        session_manager.add_message("sid-001", "user", "第一个问题很长很长很长很长")
        session_manager.add_message("sid-001", "assistant", "答案")
        session_manager.add_message("sid-001", "user", "第二个问题")
        session = session_manager.get_or_create("sid-001")
        assert session.title == "第一个问题很长很长很长很长"[:20]

    def test_add_message_updates_timestamp(self, session_manager):
        """添加消息更新 updated_at 时间戳"""
        session = session_manager.get_or_create("sid-001")
        old_updated = session.updated_at
        # 等待微小时间差
        import time
        time.sleep(0.01)
        session_manager.add_message("sid-001", "user", "新问题")
        assert session.updated_at > old_updated

    def test_add_message_with_metadata(self, session_manager):
        """添加消息时可携带 metadata"""
        session_manager.add_message("sid-001", "assistant", "答案", metadata={
            "company_name": "中芯国际",
            "question_category": "fact_extraction"
        })
        session = session_manager.get_or_create("sid-001")
        assert session.messages[0].metadata["company_name"] == "中芯国际"


# ============================================================
# 历史消息截断策略
# ============================================================

class TestHistoryTruncation:
    """锁定 v2-spec 1.3: 对话历史截断策略"""

    def test_no_history_for_new_session(self, session_manager):
        """新会话无历史消息"""
        history = session_manager.get_history_messages("new-session")
        assert history == []

    def test_single_user_message_no_history(self, session_manager):
        """只有用户消息没有助手回复时，不返回历史"""
        session_manager.add_message("sid-001", "user", "问题")
        history = session_manager.get_history_messages("sid-001")
        assert history == []

    def test_one_round_returns_history(self, session_manager):
        """一轮完整对话（user+assistant）返回历史"""
        session_manager.add_message("sid-001", "user", "问题1")
        session_manager.add_message("sid-001", "assistant", "答案1")
        history = session_manager.get_history_messages("sid-001")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_history_truncated_to_max_rounds(self, session_manager):
        """超过 max_history_rounds 时截断最早的历史"""
        # max_history_rounds=5，添加 7 轮
        for i in range(7):
            session_manager.add_message("sid-001", "user", f"问题{i+1}")
            session_manager.add_message("sid-001", "assistant", f"答案{i+1}")

        history = session_manager.get_history_messages("sid-001")
        # 最多 5 轮 = 10 条消息
        assert len(history) <= 10
        # 最早的历史被截断，应从第3轮开始
        assert history[0]["content"] == "问题3"

    def test_history_format_is_llm_messages(self, populated_manager):
        """历史消息格式为 LLM messages 数组"""
        manager, sid = populated_manager
        history = manager.get_history_messages(sid)
        for msg in history:
            assert "role" in msg
            assert "content" in msg
            assert msg["role"] in ("user", "assistant")

    def test_single_message_over_char_limit_truncated(self, session_manager):
        """单条消息超过字符限制时截断并添加标记"""
        long_content = "A" * 4000  # 超过 SINGLE_MSG_MAX=3000
        session_manager.add_message("sid-001", "user", "问题")
        session_manager.add_message("sid-001", "assistant", long_content)
        history = session_manager.get_history_messages("sid-001")
        # 助手消息应被截断
        assistant_msg = [m for m in history if m["role"] == "assistant"][0]
        assert len(assistant_msg["content"]) <= 3010  # 3000 + "...(已截断)"
        assert "已截断" in assistant_msg["content"]

    def test_total_chars_over_limit_truncates_from_head(self, session_manager):
        """总字符数超限时从最早的消息开始截断"""
        # 添加多条长消息，使总字符数超过 MAX_CHARS=6000
        for i in range(5):
            session_manager.add_message("sid-001", "user", f"问题{i+1} " + "X" * 1500)
            session_manager.add_message("sid-001", "assistant", f"答案{i+1} " + "Y" * 1500)

        history = session_manager.get_history_messages("sid-001")
        total_chars = sum(len(m["content"]) for m in history)
        assert total_chars <= 6010  # 允许微小溢出（单条截断后）


# ============================================================
# 会话列表
# ============================================================

class TestSessionList:
    """锁定 v2-spec 3.2: GET /api/sessions 行为"""

    def test_list_sessions_empty(self, session_manager):
        """无会话时返回空列表"""
        result = session_manager.list_sessions()
        assert result == []

    def test_list_sessions_sorted_by_updated_at(self, session_manager):
        """会话列表按 updated_at 倒序排列"""
        session_manager.add_message("sid-001", "user", "第一个问题")
        session_manager.add_message("sid-002", "user", "第二个问题")
        session_manager.add_message("sid-003", "user", "第三个问题")

        result = session_manager.list_sessions()
        assert len(result) == 3
        # 最新的排在前面
        assert result[0]["id"] == "sid-003"
        assert result[2]["id"] == "sid-001"

    def test_list_sessions_structure(self, populated_manager):
        """会话列表条目包含必要字段"""
        manager, sid = populated_manager
        result = manager.list_sessions()
        assert len(result) == 1
        item = result[0]
        assert "id" in item
        assert "title" in item
        assert "last_message" in item
        assert "updated_at" in item
        assert "message_count" in item

    def test_list_sessions_last_message_preview(self, populated_manager):
        """last_message 为最后一条消息的前30字"""
        manager, sid = populated_manager
        result = manager.list_sessions()
        # 最后一条是 assistant 消息
        assert result[0]["last_message"] == "2024年营收577.96亿元"[:30]

    def test_list_sessions_message_count(self, populated_manager):
        """message_count 包含所有消息"""
        manager, sid = populated_manager
        result = manager.list_sessions()
        assert result[0]["message_count"] == 4


# ============================================================
# 会话详情
# ============================================================

class TestSessionDetail:
    """锁定 v2-spec 3.3: GET /api/sessions/{id} 行为"""

    def test_get_session_detail_exists(self, populated_manager):
        """存在的会话返回完整详情"""
        manager, sid = populated_manager
        detail = manager.get_session_detail(sid)
        assert detail is not None
        assert detail["id"] == sid
        assert len(detail["messages"]) == 4
        assert "created_at" in detail
        assert "updated_at" in detail

    def test_get_session_detail_not_exists(self, session_manager):
        """不存在的会话返回 None"""
        detail = session_manager.get_session_detail("nonexistent")
        assert detail is None

    def test_session_detail_messages_structure(self, populated_manager):
        """消息条目包含 role, content, created_at, metadata"""
        manager, sid = populated_manager
        detail = manager.get_session_detail(sid)
        for msg in detail["messages"]:
            assert "role" in msg
            assert "content" in msg
            assert "created_at" in msg
            assert "metadata" in msg


# ============================================================
# 会话删除
# ============================================================

class TestSessionDeletion:
    """锁定 v2-spec 3.4: DELETE /api/sessions/{id} 行为"""

    def test_delete_session(self, session_manager):
        """删除会话后无法再获取"""
        session_manager.add_message("sid-001", "user", "问题")
        session_manager.delete_session("sid-001")
        assert session_manager.get_session_detail("sid-001") is None

    def test_delete_nonexistent_session_no_error(self, session_manager):
        """删除不存在的会话不报错"""
        session_manager.delete_session("nonexistent")  # 不应抛异常

    def test_delete_session_not_in_list(self, session_manager):
        """删除后会话列表中不再出现"""
        session_manager.add_message("sid-001", "user", "问题1")
        session_manager.add_message("sid-002", "user", "问题2")
        session_manager.delete_session("sid-001")
        result = session_manager.list_sessions()
        assert len(result) == 1
        assert result[0]["id"] == "sid-002"


# ============================================================
# 会话重命名
# ============================================================

class TestSessionRename:
    """锁定 v2-spec 3.5: PATCH /api/sessions/{id} 行为"""

    def test_rename_session(self, session_manager):
        """重命名会话标题"""
        session_manager.add_message("sid-001", "user", "原始问题")
        session_manager.rename_session("sid-001", "新标题")
        session = session_manager.get_or_create("sid-001")
        assert session.title == "新标题"

    def test_rename_nonexistent_session_no_error(self, session_manager):
        """重命名不存在的会话不报错"""
        session_manager.rename_session("nonexistent", "标题")  # 不应抛异常

    def test_rename_updates_timestamp(self, session_manager):
        """重命名更新 updated_at"""
        session_manager.add_message("sid-001", "user", "问题")
        session = session_manager.get_or_create("sid-001")
        old_updated = session.updated_at
        import time
        time.sleep(0.01)
        session_manager.rename_session("sid-001", "新标题")
        assert session.updated_at > old_updated


# ============================================================
# 过期清理
# ============================================================

class TestSessionExpiry:
    """锁定 v2-spec 1.2: 会话过期清理"""

    def test_cleanup_expired_sessions(self, session_manager):
        """超过 24h 的会话被清理"""
        session_manager.add_message("sid-001", "user", "问题")
        # 手动将 updated_at 设为 25 小时前
        session = session_manager.get_or_create("sid-001")
        session.updated_at = datetime.now() - timedelta(hours=25)

        session_manager.cleanup_expired(max_age_hours=24)
        assert session_manager.get_session_detail("sid-001") is None

    def test_cleanup_keeps_recent_sessions(self, session_manager):
        """未过期的会话保留"""
        session_manager.add_message("sid-001", "user", "问题")
        session_manager.cleanup_expired(max_age_hours=24)
        assert session_manager.get_session_detail("sid-001") is not None

    def test_cleanup_partial_expiry(self, session_manager):
        """只清理过期的，保留未过期的"""
        session_manager.add_message("sid-001", "user", "旧问题")
        session_manager.add_message("sid-002", "user", "新问题")

        # 只让 sid-001 过期
        session_manager.get_or_create("sid-001").updated_at = datetime.now() - timedelta(hours=25)

        session_manager.cleanup_expired(max_age_hours=24)
        assert session_manager.get_session_detail("sid-001") is None
        assert session_manager.get_session_detail("sid-002") is not None


# ============================================================
# 消息上限
# ============================================================

class TestMessageLimit:
    """锁定 v2-spec 1.2: 每会话最多 50 条用户消息"""

    def test_count_user_messages(self, session_manager):
        """正确统计用户消息数"""
        session_manager.add_message("sid-001", "user", "问题1")
        session_manager.add_message("sid-001", "assistant", "答案1")
        session_manager.add_message("sid-001", "user", "问题2")
        session = session_manager.get_or_create("sid-001")
        assert session.count_user_messages() == 2

    def test_session_reaches_limit(self, session_manager):
        """达到 50 条用户消息上限"""
        for i in range(50):
            session_manager.add_message("sid-001", "user", f"问题{i+1}")
            session_manager.add_message("sid-001", "assistant", f"答案{i+1}")

        session = session_manager.get_or_create("sid-001")
        assert session.count_user_messages() == 50
        assert session.count_user_messages() >= session_manager.max_user_messages
