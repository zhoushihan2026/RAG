# v2 Spec: 多轮对话记忆 + 对话历史管理

> 版本: v2
> 基于: v1 (单轮对话，无记忆，居中单栏布局)
> 生成日期: 2026-06-06
> 范围: 仅包含功能 1（多轮对话记忆）和功能 2（对话历史管理）
> v3 功能（知识库管理增强、检索结果可视化、用户反馈、多知识库）不在本 spec 范围内

---

## 0. v1 现状回顾

| 项目 | v1 行为 |
|------|---------|
| 每次提问 | 独立处理，不读取也不写入会话历史 |
| session_id | 请求中有此字段，但后端忽略 |
| 前端布局 | 单栏居中，无侧边栏 |
| 消息持久化 | 仅在 React state 中，刷新页面丢失 |
| LLM 调用 | `send_message_stream(system_content, human_content)` — 只传当前轮的 system + user |
| Prompt 构建 | `user_prompt.format(context=rag_context, question=question)` — question 为原始问题，无历史 |

---

## 1. 多轮对话记忆

### 1.1 核心需求

- 用户可以追问，如 "它的营收呢？"，系统能理解 "它" 指代上一轮提到的公司
- 每次提问不再独立，而是携带对话历史作为上下文传入 LLM
- 需要设计对话历史的存储、截断和传入策略

### 1.2 对话历史存储策略

#### 后端存储（内存 + 可选持久化）

```
SessionManager (单例，挂载在 app.state)
├── sessions: dict[str, Session]
│
Session
├── session_id: str
├── created_at: datetime
├── updated_at: datetime
├── title: str                    # 会话标题（首条用户消息的前 20 字符）
└── messages: list[SessionMessage]
    │
    SessionMessage
    ├── role: "user" | "assistant"
    ├── content: str              # 用户原始问题 或 助手最终答案
    ├── created_at: datetime
    └── metadata: dict (可选)     # company_name, question_category 等
```

- **存储位置**: 内存字典，进程重启后丢失
- **容量限制**: 每个会话最多保留 50 条用户消息（约 25 轮对话，含助手回复共约 100 条），超出时提示用户新开会话
- **会话过期**: 最后活跃时间超过 24 小时的会话可被清理（惰性清理，非定时任务）

#### 前端存储（localStorage）

- 前端在 localStorage 中保存会话列表和消息，用于页面刷新后恢复
- 存储结构: `{ sessions: SessionSummary[], activeSessionId: string }`
- SessionSummary: `{ id, title, lastMessage, updatedAt }`
- 完整消息内容从后端 API 获取，localStorage 仅存摘要

### 1.3 对话历史截断策略

LLM 有上下文窗口限制，需要截断历史消息:

```
截断规则:
1. 始终保留 system prompt（不在历史消息中，单独传入）
2. 始终保留最近 N 轮对话（默认 N=5，即最近 5 组 user+assistant）
3. 历史消息总 token 数不超过阈值（默认 4000 tokens）
4. 截断时从最早的消息开始删除
5. 如果单条消息超过 2000 tokens，截断该消息内容（保留前 2000 tokens + "...(已截断)"）

估算方式:
- 中文: 1 字符 ≈ 1.5 tokens
- 英文: 1 单词 ≈ 1.3 tokens
- 使用简单字符数估算，不依赖 tiktoken（避免额外依赖）
```

### 1.4 对话历史传入 LLM 的方式

当前 `send_message_stream` 接受 `system_content` 和 `human_content` 两个参数，内部构造 messages 数组。

v2 扩展为支持传入完整 messages 数组:

```python
# api_requests.py 新增方法
def send_message_stream_with_history(
    self,
    model: str,
    messages: list[dict],   # 完整的 messages 数组
    temperature: float = 0.1,
):
    """
    流式发送消息，支持多轮对话历史。
    messages 格式: [{"role": "system/user/assistant", "content": "..."}]
    """
    # 复用现有的 DashScope/OpenAI 兼容接口逻辑
    # 仅将 messages 直接传入，不再手动拼接 system + human
```

### 1.5 Pipeline 层改造

`answer_single_question_stream` 新增 `session_id` 参数:

```python
def answer_single_question_stream(
    self,
    question: str,
    kind: str = "string",
    session_id: str | None = None,   # v2 新增
):
```

**改造要点**:

1. 如果 `session_id` 不为 None，从 `SessionManager` 获取历史消息
2. 构建 LLM messages 数组时，在 system prompt 之后、当前 user prompt 之前，插入历史消息
3. 历史消息格式:
   ```python
   history_messages = []
   for msg in session.messages[-N:]:
       history_messages.append({"role": msg.role, "content": msg.content})
   ```
4. 当前轮的 user prompt 仍然包含 RAG context，但 question 部分改为包含历史上下文的增强版:

```
原始 user_prompt: "上下文: {context}\n\n问题: {question}"
v2 user_prompt:   "上下文: {context}\n\n对话历史:\n{history}\n\n当前问题: {question}"
```

5. 回答完成后，将当前轮的 user question 和 assistant final_answer 存入 Session

### 1.6 问题重写增强

v1 的问题重写是独立的，不考虑历史。v2 在问题重写时注入历史上下文:

```
v1 重写 prompt:
  "请重写以下问题: {question}"

v2 重写 prompt:
  "以下是之前的对话历史:
   {history_summary}
   
   请根据对话历史，重写用户的当前问题，使其成为独立完整的问题:
   当前问题: {question}"
```

- `history_summary`: 最近 3 轮对话的摘要（用户问 + 助手答的前 100 字）
- 这样 "它的营收呢？" 会被重写为 "中芯国际2024年的营收是多少？"

### 1.7 API 变更

#### POST /api/chat 变更

```json
// 请求
{
  "question": "它的营收呢？",
  "session_id": "abc123"           // v2: 必填，前端生成或从会话列表获取
}
```

| 字段 | v1 | v2 |
|------|----|----|
| question | 必填 | 必填 |
| session_id | 可选(忽略) | 必填 |

- 如果 session_id 对应的会话不存在，自动创建新会话
- session_id 由前端生成（UUID v4），首次提问时生成

#### 新增 API

```
GET    /api/sessions              # 获取会话列表
GET    /api/sessions/{id}         # 获取会话详情（含消息历史）
DELETE /api/sessions/{id}         # 删除会话
PATCH  /api/sessions/{id}         # 更新会话（重命名标题）
```

详见下方第 3 节。

---

## 2. 对话历史管理（侧边栏）

### 2.1 布局变更

v1 是单栏居中布局，无侧边栏。v2 新增左侧侧边栏:

```
+----------+--------------------------------------------------+
|          |  品牌栏 (极简)                                    |
|  侧边栏  +--------------------------------------------------+
|          |                                                  |
| [新建对话] |              对话消息区 (居中)                    |
|          |              max-width: 768px                    |
| 会话1    |                                                  |
| 会话2    |    用户消息 (右对齐)                               |
| 会话3    |    助手消息 (左对齐)                               |
| ...      |                                                  |
|          |                                                  |
|          +--------------------------------------------------+
|          |          底部输入区 (固定在底部)                    |
+----------+--------------------------------------------------+
```

### 2.2 侧边栏规格

| 属性 | 值 |
|------|-----|
| 宽度 | 260px |
| 背景 | #F8FAFC |
| 右边框 | 1px solid #E2E8F0 |
| 位置 | 固定左侧，不随对话区滚动 |
| 可折叠 | 是，点击品牌栏左侧的汉堡按钮切换 |
| 默认状态 | 桌面端展开，移动端折叠 |

### 2.3 侧边栏内容

```
Sidebar
├── SidebarHeader
│   ├── NewChatButton          # "新建对话" 按钮
│   └── CollapseButton         # 折叠侧边栏按钮 (移动端)
│
└── SessionList                # 会话列表 (可滚动)
    └── SessionItem            # 单个会话条目
        ├── SessionTitle       # 会话标题 (首条用户消息前 20 字)
        ├── SessionTime        # 最后活跃时间 (相对时间: "3分钟前")
        ├── SessionPreview     # 最后一条消息预览 (前 30 字)
        └── SessionMenu        # 右键/三点菜单
            ├── 重命名
            └── 删除
```

### 2.4 SessionItem 规格

| 属性 | 值 |
|------|-----|
| 高度 | 自适应，最小 56px |
| 内边距 | 12px 16px |
| 选中状态 | 背景 #E2E8F0，左侧 3px 蓝色竖线 |
| hover 状态 | 背景 #F1F5F9 |
| 标题 | 字号 13px，字重 500，颜色 #1E293B，单行截断 |
| 时间 | 字号 11px，颜色 #94A3B8 |
| 预览 | 字号 12px，颜色 #64748B，单行截断 |
| 菜单触发 | hover 时右侧显示三点图标 |

### 2.5 新建对话按钮

| 属性 | 值 |
|------|-----|
| 位置 | 侧边栏顶部 |
| 外观 | 圆角矩形，背景 #2563EB，文字白色 |
| 文字 | "+ 新建对话" |
| 字号 | 13px |
| 内边距 | 8px 16px |
| 点击行为 | 创建新会话，清空对话区，切换到欢迎页 |

### 2.6 会话操作

#### 新建对话

```
用户点击 "新建对话"
  → 前端生成新 session_id (UUID v4)
  → 清空当前对话区，显示欢迎页
  → 侧边栏顶部新增一个会话条目（标题为 "新对话"）
  → 用户首次提问后，标题自动更新为问题前 20 字
```

#### 切换会话

```
用户点击侧边栏某个会话
  → 从后端 GET /api/sessions/{id} 获取完整消息历史
  → 渲染消息到对话区
  → 侧边栏高亮当前会话
```

#### 重命名会话

```
用户点击三点菜单 → 重命名
  → SessionTitle 变为可编辑 input
  → 回车或失焦保存
  → PATCH /api/sessions/{id} 更新标题
```

#### 删除会话

```
用户点击三点菜单 → 删除
  → 弹出确认对话框 "确定删除此对话？"
  → 确认后 DELETE /api/sessions/{id}
  → 侧边栏移除该条目
  → 如果删除的是当前会话，切换到欢迎页
```

### 2.7 前端状态管理变更

v1 的全局状态只有 `messages` 和 `isGenerating`。v2 新增:

```typescript
interface AppState {
  // --- v1 已有 ---
  messages: Message[];
  isGenerating: boolean;
  uploadState: 'idle' | 'uploading' | 'success' | 'error';
  selectedFile: File | null;

  // --- v2 新增 ---
  sessions: SessionSummary[];         // 会话列表摘要
  activeSessionId: string | null;     // 当前活跃会话ID
  sidebarCollapsed: boolean;          // 侧边栏是否折叠
}

interface SessionSummary {
  id: string;
  title: string;
  lastMessage: string;                // 最后一条消息预览
  updatedAt: string;                  // ISO 时间戳
  messageCount: number;               // 消息数量
}
```

### 2.8 前端组件树变更

```
App
├── Sidebar                          # v2 新增: 侧边栏
│   ├── SidebarHeader
│   │   ├── NewChatButton
│   │   └── CollapseButton
│   └── SessionList
│       └── SessionItem[]
│           ├── SessionTitle
│           ├── SessionMeta (时间+预览)
│           └── SessionMenu
│
├── MainArea                         # v2: 原来的全屏区域，现在占据侧边栏右侧
│   ├── BrandBar
│   │   └── HamburgerButton          # v2 新增: 折叠/展开侧边栏
│   ├── ChatArea (同 v1)
│   └── InputBar (同 v1)
```

---

## 3. API 契约变更

### 3.1 POST /api/chat（变更）

```json
// 请求
{
  "question": "它的营收呢？",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | 是 | 用户问题 |
| session_id | string | 是 | 会话ID，v2 必填 |

**SSE 事件流**: 同 v1，无变更。

**后端行为变更**:
1. 根据 session_id 查找 Session，不存在则创建
2. 从 Session 中提取历史消息，截断后注入 LLM prompt
3. 问题重写时考虑历史上下文
4. 回答完成后，将当前轮 Q&A 存入 Session

### 3.2 GET /api/sessions（新增）

获取会话列表，按最后活跃时间倒序。

**响应:**

```json
{
  "sessions": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "中芯国际2024年研发投入...",
      "last_message": "2024年研发投入占营业收入比例约...",
      "updated_at": "2026-06-06T10:30:00Z",
      "message_count": 4
    }
  ]
}
```

### 3.3 GET /api/sessions/{id}（新增）

获取会话详情，含完整消息历史。

**响应:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "中芯国际2024年研发投入...",
  "created_at": "2026-06-06T10:00:00Z",
  "updated_at": "2026-06-06T10:30:00Z",
  "messages": [
    {
      "role": "user",
      "content": "中芯国际2024年研发投入占营业收入的比例是多少？",
      "created_at": "2026-06-06T10:00:00Z"
    },
    {
      "role": "assistant",
      "content": "2024年研发投入占营业收入比例约...",
      "created_at": "2026-06-06T10:01:00Z",
      "metadata": {
        "company_name": "中芯国际",
        "question_category": "fact_extraction"
      }
    }
  ]
}
```

**错误响应:**

| HTTP 状态码 | 场景 |
|------------|------|
| 404 | 会话不存在 |

### 3.4 DELETE /api/sessions/{id}（新增）

删除会话及其所有消息。

**响应:**

```json
{
  "status": "deleted"
}
```

| HTTP 状态码 | 场景 |
|------------|------|
| 404 | 会话不存在 |

### 3.5 PATCH /api/sessions/{id}（新增）

更新会话属性（目前仅支持重命名标题）。

**请求:**

```json
{
  "title": "中芯国际研发投入分析"
}
```

**响应:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "中芯国际研发投入分析",
  "updated_at": "2026-06-06T10:35:00Z"
}
```

---

## 4. 后端实现要点

### 4.1 SessionManager 类

```python
class SessionManager:
    """会话管理器，挂载在 app.state.session_manager"""
    
    def __init__(self, max_user_messages_per_session=50, max_history_rounds=5):
        self.sessions: dict[str, Session] = {}
        self.max_user_messages = max_user_messages_per_session
        self.max_history_rounds = max_history_rounds
    
    def get_or_create(self, session_id: str) -> Session:
        """获取或创建会话"""
    
    def get_history_messages(self, session_id: str) -> list[dict]:
        """获取截断后的历史消息，格式为 LLM messages 数组"""
    
    def add_message(self, session_id: str, role: str, content: str, metadata: dict = None):
        """添加消息到会话"""
    
    def delete_session(self, session_id: str):
        """删除会话"""
    
    def rename_session(self, session_id: str, title: str):
        """重命名会话"""
    
    def list_sessions(self) -> list[SessionSummary]:
        """获取会话列表摘要"""
    
    def cleanup_expired(self, max_age_hours=24):
        """清理过期会话（惰性调用）"""
```

### 4.2 Pipeline 改造

`answer_single_question_stream` 新增参数:

```python
def answer_single_question_stream(
    self,
    question: str,
    kind: str = "string",
    session_id: str | None = None,        # v2 新增
    history_messages: list[dict] | None = None,  # v2 新增: 外部传入的历史消息
):
```

- `session_id`: 用于标识会话（由 API 层使用）
- `history_messages`: 由 API 层从 SessionManager 获取并传入，Pipeline 不直接依赖 SessionManager

**Prompt 构建变更**:

```python
# v1
user_prompt = selected_prompt.user_prompt.format(
    context=rag_context, question=question
)

# v2
if history_messages:
    # 格式化历史对话
    history_text = self._format_history_for_prompt(history_messages)
    user_prompt = selected_prompt.user_prompt.format(
        context=rag_context, question=question, history=history_text
    )
else:
    user_prompt = selected_prompt.user_prompt.format(
        context=rag_context, question=question, history=""
    )
```

**LLM 调用变更**:

```python
# v1
for token in dashscope_processor.send_message_stream(
    model=self.run_config.answering_model,
    system_content=system_prompt,
    human_content=user_prompt
):

# v2
if history_messages:
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_prompt})
    for token in dashscope_processor.send_message_stream_with_history(
        model=self.run_config.answering_model,
        messages=messages,
    ):
else:
    # 无历史时保持 v1 行为
    for token in dashscope_processor.send_message_stream(
        model=self.run_config.answering_model,
        system_content=system_prompt,
        human_content=user_prompt
    ):
```

### 4.3 问题重写改造

`_rewrite_and_classify_parallel` 需要接受历史上下文:

```python
def _rewrite_and_classify_parallel(self, question: str, history_messages: list[dict] | None = None):
    """
    v2: 问题重写时考虑历史上下文
    """
    if history_messages:
        # 构建包含历史的重写 prompt
        history_summary = self._summarize_history(history_messages, max_rounds=3)
        rewrite_prompt = REWRITE_WITH_HISTORY_PROMPT.format(
            history=history_summary, question=question
        )
    else:
        rewrite_prompt = REWRITE_PROMPT.format(question=question)
    # ... 其余逻辑不变
```

---

## 5. 前端实现要点

### 5.1 App.tsx 状态管理变更

```typescript
// v2 新增状态
const [sessions, setSessions] = useState<SessionSummary[]>([]);
const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

// handleSubmit 变更: 传入 session_id
const handleSubmit = useCallback(async (question: string) => {
  // 如果没有活跃会话，创建新会话
  let sessionId = activeSessionId;
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    setActiveSessionId(sessionId);
  }
  // 发送请求时携带 session_id
  await sendQuestion(question, sessionId, (event) => { ... });
}, [isGenerating, activeSessionId]);
```

### 5.2 api/index.ts 变更

```typescript
// sendQuestion 新增 sessionId 参数
export async function sendQuestion(
  question: string,
  sessionId: string,           // v2 新增
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId }),
  });
  // ... 其余不变
}

// 新增 API
export async function getSessions(): Promise<{ sessions: SessionSummary[] }> { ... }
export async function getSession(id: string): Promise<SessionDetail> { ... }
export async function deleteSession(id: string): Promise<void> { ... }
export async function renameSession(id: string, title: string): Promise<void> { ... }
```

### 5.3 types/index.ts 变更

```typescript
// v2 新增类型
export interface SessionSummary {
  id: string;
  title: string;
  last_message: string;
  updated_at: string;
  message_count: number;
}

export interface SessionMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
  metadata?: {
    company_name?: string;
    question_category?: string;
  };
}

export interface SessionDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: SessionMessage[];
}
```

### 5.4 页面初始化流程

```
App 挂载
  → GET /api/sessions 获取会话列表
  → 渲染侧边栏
  → 如果有会话，默认选中最近一个
  → 如果无会话，显示欢迎页
```

### 5.5 会话切换流程

```
用户点击侧边栏会话
  → GET /api/sessions/{id} 获取完整消息
  → 将 SessionMessage[] 转换为 Message[] 渲染到对话区
  → 更新 activeSessionId
```

### 5.6 HintText 变更

```
v1: "基于 RAG 知识库回答，每次提问独立，不保留上下文"
v2: "基于 RAG 知识库回答，支持多轮对话追问"
```

---

## 6. v1 兼容性

| 项目 | v1 行为 | v2 行为 |
|------|---------|---------|
| session_id 缺失 | 忽略 | 后端自动生成（兼容旧前端） |
| 无历史消息 | 正常单轮 | 同 v1，history_messages 为空 |
| 侧边栏 | 不存在 | 默认展开，可折叠 |
| 消息持久化 | 刷新丢失 | 后端内存存储 + 前端 localStorage 缓存 |

---

## 7. 不在 v2 范围内的功能

以下功能属于 v3，本 spec 不涉及:

- 知识库管理增强（在线查看文档列表、删除文档、处理状态、统计信息）
- 检索结果可视化（命中片段、相似度分数、关键词高亮、跳转原文）
- 用户反馈机制（点赞/点踩、反馈持久化）
- 多知识库支持（多知识库创建、选择、隔离）

---

## 8. 测试要点

### 8.1 后端测试

| 测试场景 | 验证点 |
|---------|--------|
| 新会话首次提问 | session_id 不存在时自动创建，返回正常 SSE 流 |
| 多轮对话上下文传递 | 第二轮提问时，LLM 收到的 messages 包含第一轮的 Q&A |
| 历史截断 | 超过 5 轮时，最早的历史被截断 |
| 指代消解 | "它的营收呢？" 被重写为包含公司名的完整问题 |
| 会话列表 | GET /api/sessions 返回按时间倒序的列表 |
| 会话详情 | GET /api/sessions/{id} 返回完整消息历史 |
| 删除会话 | DELETE 后再次 GET 返回 404 |
| 重命名会话 | PATCH 后标题更新 |
| 过期清理 | 超过 24h 未活跃的会话被清理 |
| 无历史时兼容 | session_id 存在但无历史消息时，行为同 v1 |

### 8.2 前端测试

| 测试场景 | 验证点 |
|---------|--------|
| 侧边栏渲染 | 会话列表正确显示 |
| 新建对话 | 点击后清空对话区，生成新 session_id |
| 切换会话 | 点击后加载历史消息到对话区 |
| 删除会话 | 确认后侧边栏移除，对话区清空 |
| 重命名会话 | 编辑后标题更新 |
| 折叠侧边栏 | 汉堡按钮切换侧边栏显隐 |
| 多轮对话 UI | 追问时消息追加到当前会话 |
| 刷新恢复 | 刷新页面后会话列表和当前对话恢复 |
