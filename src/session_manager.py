"""
会话管理模块
管理多轮对话的会话创建、消息存储、历史截断等逻辑
"""
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionMessage:
    """会话中的单条消息"""
    role: str                          # "user" | "assistant"
    content: str
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


@dataclass
class Session:
    """单个会话"""
    session_id: str
    title: str = "新对话"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    messages: list[SessionMessage] = field(default_factory=list)

    def count_user_messages(self) -> int:
        """统计用户消息数量"""
        return sum(1 for m in self.messages if m.role == "user")

    def add_message(self, role: str, content: str, metadata: dict = None):
        """添加消息到会话"""
        self.messages.append(SessionMessage(
            role=role, content=content,
            metadata=metadata or {}
        ))
        self.updated_at = datetime.now()
        # 首条用户消息自动设置标题
        if role == "user" and self.title == "新对话":
            self.title = content[:20]


class SessionManager:
    """会话管理器，挂载在 app.state.session_manager"""

    def __init__(self, max_user_messages_per_session=50, max_history_rounds=5):
        self.sessions: dict[str, Session] = {}
        self.max_user_messages = max_user_messages_per_session
        self.max_history_rounds = max_history_rounds

    def get_or_create(self, session_id: str) -> Session:
        """获取或创建会话"""
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id=session_id)
        return self.sessions[session_id]

    def get_history_messages(self, session_id: str) -> list[dict]:
        """
        获取截断后的历史消息，格式为 LLM messages 数组。
        不包含当前轮，仅包含之前的对话。
        """
        session = self.sessions.get(session_id)
        if not session or len(session.messages) < 2:
            return []

        # 截断：取最近 N 轮（1轮 = 1 user + 1 assistant）
        max_msgs = self.max_history_rounds * 2
        recent_messages = session.messages[-max_msgs:]

        # token 截断：总字符数不超过阈值
        MAX_CHARS = 6000   # 约 4000 tokens（中文 1.5 字符/token）
        SINGLE_MSG_MAX = 3000  # 约 2000 tokens

        result = []
        total_chars = 0
        # 从尾部开始遍历，确保保留最近的消息
        for msg in reversed(recent_messages):
            content = msg.content
            if len(content) > SINGLE_MSG_MAX:
                content = content[:SINGLE_MSG_MAX] + "...(已截断)"
            if total_chars + len(content) > MAX_CHARS:
                break
            result.append({"role": msg.role, "content": content})
            total_chars += len(content)
        # 恢复原始顺序
        result.reverse()

        return result

    def add_message(self, session_id: str, role: str, content: str, metadata: dict = None):
        """添加消息到会话"""
        session = self.get_or_create(session_id)
        session.add_message(role, content, metadata)

    def delete_session(self, session_id: str):
        """删除会话"""
        self.sessions.pop(session_id, None)

    def rename_session(self, session_id: str, title: str):
        """重命名会话"""
        session = self.sessions.get(session_id)
        if session:
            session.title = title
            session.updated_at = datetime.now()

    def list_sessions(self) -> list[dict]:
        """获取会话列表摘要，按 updated_at 倒序"""
        items = []
        for s in self.sessions.values():
            last_msg = ""
            if s.messages:
                last_msg = s.messages[-1].content[:30]
            items.append({
                "id": s.session_id,
                "title": s.title,
                "last_message": last_msg,
                "updated_at": s.updated_at.isoformat() + "Z",
                "message_count": len(s.messages),
            })
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items

    def get_session_detail(self, session_id: str) -> Optional[dict]:
        """获取会话详情"""
        session = self.sessions.get(session_id)
        if not session:
            return None
        return {
            "id": session.session_id,
            "title": session.title,
            "created_at": session.created_at.isoformat() + "Z",
            "updated_at": session.updated_at.isoformat() + "Z",
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() + "Z",
                    "metadata": m.metadata,
                }
                for m in session.messages
            ],
        }

    def cleanup_expired(self, max_age_hours=24):
        """清理过期会话（惰性调用）"""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        expired_ids = [
            sid for sid, s in self.sessions.items()
            if s.updated_at < cutoff
        ]
        for sid in expired_ids:
            del self.sessions[sid]
