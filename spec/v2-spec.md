# v2 Spec: 多轮对话记忆 + 对话历史管理

> 版本: v2
> 基于: v1 (单轮对话，无记忆，居中单栏布局)
> 更新日期: 2026-06-07
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
| LLM 调用 | 只传当前轮的 system + human |
| Prompt 构建 | question 为原始问题，无历史 |

---

## 1. 多轮对话记忆

### 1.1 核心需求

- 用户可以追问，如 "它的营收呢？"，系统能理解 "它" 指代上一轮提到的公司
- 每次提问不再独立，而是携带对话历史作为上下文传入 LLM
- 需要设计对话历史的存储、截断和传入策略

### 1.2 对话历史存储策略

#### 后端存储（内存）

- SessionManager 单例，挂载在 app.state
- 存储结构: sessions 字典，key 为 session_id，value 为 Session 对象
- Session 包含: session_id, title, created_at, updated_at, messages 列表
- SessionMessage 包含: role ("user"/"assistant"), content, created_at, metadata
- 存储位置: 内存字典，进程重启后丢失
- 容量限制: 每个会话最多保留 50 条用户消息（约 25 轮对话），超出时提示用户新开会话
- 会话过期: 最后活跃时间超过 24 小时的会话可被清理（惰性清理，非定时任务）
- 首条用户消息自动设置会话标题（取前 20 字符）

#### 前端存储（localStorage）

- 前端在 localStorage 中保存会话列表和消息，用于页面刷新后恢复
- 存储结构: sessions 摘要列表 + activeSessionId
- 完整消息内容从后端 API 获取，localStorage 仅存摘要

### 1.3 对话历史截断策略

LLM 有上下文窗口限制，需要截断历史消息:

- 始终保留 system prompt（不在历史消息中，单独传入）
- 始终保留最近 N 轮对话（默认 N=5，即最近 5 组 user+assistant）
- 历史消息总字符数不超过 6000 字符（约 4000 tokens）
- 截断时从最早的消息开始删除
- 如果单条消息超过 3000 字符，截断该消息内容（保留前 3000 字符 + "...(已截断)"）
- 使用简单字符数估算，不依赖 tiktoken

### 1.4 对话历史传入 LLM 的方式

send_message_stream 方法已支持传入完整 messages 数组（通过 messages 参数），无需单独的方法。

- 当传入 messages 参数时，直接使用该数组
- 当未传入 messages 时，从 system_content + human_content 构造
- 两种处理器（BaseDashscopeProcessor、Fe8Processor）均支持此接口

### 1.5 Pipeline 层改造

answer_single_question_stream 接受 history_messages 参数（由 API 层从 SessionManager 获取并传入）。

**改造要点**:

1. API 层从 SessionManager 获取截断后的历史消息，传入 pipeline
2. 构建 LLM messages 数组时，在 system prompt 之后、当前 user prompt 之前，插入历史消息
3. 回答完成后，API 层将当前轮的 user question 和 assistant final_answer 存入 Session

### 1.6 问题重写增强

v2 在问题重写时注入历史上下文，使用专门的 HISTORY_REWRITE_SYSTEM_PROMPT：

- 根据对话历史将代词替换为实际实体
- 将省略的主语和时间范围补充完整
- 进行关键词扩展以提升检索召回率
- 处理歧义追问：补全后的问题选择最可能的指标，但 rewritten_query 中包含所有可能相关的指标关键词

**重写输出格式**（JSON）:

- completed_question: 补全后的完整问题（自然语言，可直接独立理解）
- rewritten_query: 补全并扩展后的关键词（用空格分隔，用于检索）
- doc_type: 文档类型（年报/券商研报/调研纪要/null）

### 1.7 追问检索增强

追问场景下，除了重写问题外，还通过 expand_followup_query 函数增强检索：

- 从前一轮用户问题中提取有意义的中文词组，合并到检索查询中
- 使用财务/业务指标词表匹配（营业收入、毛利率、同比增长等），避免滑动窗口产生碎片
- 提取数字+单位组合（如"2024年"）
- 只取前一轮问题中不在当前 rewritten_query 中的关键词
- 过滤停用词

### 1.8 回答时使用补全后的问题

回答 LLM 接收的是 completed_question（补全后的完整问题），而非原始问题：

- 避免回答 LLM 看到歧义问题（如"它的毛利率呢？"）而答偏
- 如果重写结果中没有 completed_question，回退使用原始问题

### 1.9 回答分段与保存

所有回答 prompt 的 final_answer 字段要求分段输出：

- 用空行（双换行）分隔不同要点
- 不同指标或数据应分段呈现
- 核心结论与补充说明应分段
- 前端 simpleMarkdown 函数已支持双换行分段渲染

回答保存到会话时的回退策略：

- 优先保存 final_answer
- 如果 final_answer 为空，回退使用 step_by_step_analysis
- 如果两者都为空，保存"回答生成失败"

### 1.10 API 变更

#### POST /api/chat 变更

| 字段 | v1 | v2 |
|------|----|----|
| question | 必填 | 必填 |
| session_id | 可选(忽略) | 可选（未提供时自动生成 UUID） |

- 如果 session_id 对应的会话不存在，自动创建新会话

#### 新增 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/sessions | 获取会话列表 |
| GET | /api/sessions/{id} | 获取会话详情（含消息历史） |
| DELETE | /api/sessions/{id} | 删除会话 |
| PATCH | /api/sessions/{id} | 更新会话（重命名标题） |

详见下方第 3 节。

---

## 2. 对话历史管理（侧边栏）

### 2.1 布局变更

v1 是单栏居中布局，无侧边栏。v2 新增左侧侧边栏:

- 左侧侧边栏 260px，背景 #F8FAFC，右边框 1px solid #E2E8F0
- 固定左侧，不随对话区滚动
- 可折叠，点击品牌栏左侧的汉堡按钮切换
- 桌面端默认展开，移动端默认折叠

### 2.2 侧边栏内容

- SidebarHeader: 新建对话按钮 + 折叠按钮
- SessionList: 可滚动的会话列表
  - SessionItem: 标题（首条用户消息前 20 字）、时间（相对时间）、预览（前 30 字）、三点菜单（重命名/删除）

### 2.3 SessionItem 规格

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

### 2.4 新建对话按钮

| 属性 | 值 |
|------|-----|
| 位置 | 侧边栏顶部 |
| 外观 | 圆角矩形，背景 #2563EB，文字白色 |
| 文字 | "+ 新建对话" |
| 字号 | 13px |
| 内边距 | 8px 16px |
| 点击行为 | 创建新会话，清空对话区，切换到欢迎页 |

### 2.5 会话操作

#### 新建对话

- 前端生成新 session_id (UUID v4)
- 清空当前对话区，显示欢迎页
- 侧边栏顶部新增一个会话条目（标题为 "新对话"）
- 用户首次提问后，标题自动更新为问题前 20 字

#### 切换会话

- 从后端 GET /api/sessions/{id} 获取完整消息历史
- 渲染消息到对话区
- 侧边栏高亮当前会话

#### 重命名会话

- 点击三点菜单 → 重命名
- SessionTitle 变为可编辑 input
- 回车或失焦保存
- PATCH /api/sessions/{id} 更新标题

#### 删除会话

- 点击三点菜单 → 删除
- 弹出确认对话框
- 确认后 DELETE /api/sessions/{id}
- 侧边栏移除该条目
- 如果删除的是当前会话，切换到欢迎页

### 2.6 前端状态管理变更

v2 新增状态:

- sessions: 会话列表摘要数组
- activeSessionId: 当前活跃会话ID
- sidebarCollapsed: 侧边栏是否折叠

SessionSummary 包含: id, title, lastMessage, updatedAt, messageCount

### 2.7 前端组件树变更

- App
  - Sidebar（新增）: SidebarHeader(NewChatButton, CollapseButton) + SessionList(SessionItem[])
  - MainArea: BrandBar(含HamburgerButton) + ChatArea + InputBar

---

## 3. API 契约

### 3.1 POST /api/chat

**请求:**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | 是 | 用户问题 |
| session_id | string | 否 | 会话ID，未提供时自动生成 |

**SSE 事件流**: 同 v1，无变更。

**后端行为:**
1. 根据 session_id 查找 Session，不存在则创建
2. 检查会话是否达到消息上限
3. 从 Session 中提取历史消息，截断后传入 pipeline
4. 保存用户问题到会话
5. 流式返回回答
6. 回答完成后保存助手回答到会话

### 3.2 GET /api/sessions

获取会话列表，按最后活跃时间倒序。

**响应:**

| 字段 | 类型 | 说明 |
|------|------|------|
| sessions | array | 会话列表 |
| sessions[].id | string | 会话ID |
| sessions[].title | string | 会话标题 |
| sessions[].last_message | string | 最后一条消息预览 |
| sessions[].updated_at | string | ISO 时间戳 |
| sessions[].message_count | number | 消息数量 |

### 3.3 GET /api/sessions/{id}

获取会话详情，含完整消息历史。

**响应:**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 会话ID |
| title | string | 会话标题 |
| created_at | string | 创建时间 |
| updated_at | string | 更新时间 |
| messages | array | 消息列表 |
| messages[].role | string | "user" 或 "assistant" |
| messages[].content | string | 消息内容 |
| messages[].created_at | string | 创建时间 |
| messages[].metadata | object | 元数据（company_name, question_category 等） |

**错误响应:** 404 - 会话不存在

### 3.4 DELETE /api/sessions/{id}

删除会话及其所有消息。

**响应:** {"status": "deleted"}

**错误响应:** 404 - 会话不存在

### 3.5 PATCH /api/sessions/{id}

更新会话属性（目前仅支持重命名标题）。

**请求:** {"title": "新标题"}

**响应:**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 会话ID |
| title | string | 更新后的标题 |
| updated_at | string | 更新时间 |

**错误响应:** 404 - 会话不存在

---

## 4. 后端实现要点

### 4.1 SessionManager 类

位于 src/session_manager.py，提供以下方法:

| 方法 | 说明 |
|------|------|
| get_or_create(session_id) | 获取或创建会话 |
| get_history_messages(session_id) | 获取截断后的历史消息（LLM messages 数组格式） |
| add_message(session_id, role, content, metadata) | 添加消息到会话 |
| delete_session(session_id) | 删除会话 |
| rename_session(session_id, title) | 重命名会话 |
| list_sessions() | 获取会话列表摘要 |
| get_session_detail(session_id) | 获取会话详情 |
| cleanup_expired(max_age_hours) | 清理过期会话 |

### 4.2 Pipeline 步骤执行顺序

v2 中，当有历史消息时，步骤之间产生新的依赖关系:

**核心问题**: 用户追问 "它的营收呢？" 不包含公司名，公司名抽取会失败。但问题重写可以把 "它" 解析为 "中芯国际"。

**v2 步骤执行顺序**:

1. **公司名抽取**: 在原始问题上尝试抽取
   - 成功 → 进入步骤2（正常流程）
   - 失败 + 有历史消息 → 先执行问题重写，再从重写后的问题中抽取公司名
   - 失败 + 无历史消息 → 回退：从历史消息中提取公司名；仍失败则返回错误

2. **问题重写 + 问题分类**: 若步骤1已执行过则跳过（复用结果），否则正常执行

3. **元数据过滤**: 构建 rewritten_query 和 metadata_filters

4. **追问检索增强**: 如果有历史消息，调用 expand_followup_query 将前一轮关键词合并到检索查询

5. **检索**: 元数据过滤检索（BM25+Vector 混合 + Rerank）

6. **上下文格式化**: 格式化检索结果

7. **流式生成**: 使用 completed_question（补全后的完整问题）而非原始问题构建 user_prompt；有历史消息时将历史注入 LLM messages 数组

8. **解析与溯源**: 解析 LLM 响应，补充溯源信息

**关键数据类型说明**:

- _rewrite_and_classify_parallel 返回 (rewrite_result: dict, question_category: str)
- rewrite_result 包含: completed_question, rewritten_query, doc_type
- completed_question 用于回答 LLM 的 user_prompt
- rewritten_query 用于检索

### 4.3 Prompt 构建与 LLM 调用

- 回答时使用 completed_question 而非原始 question，避免歧义
- 有历史消息时，构建完整 messages 数组（system + 历史消息 + 当前 user_prompt），通过 send_message_stream 的 messages 参数传入
- 无历史消息时，保持原有调用方式（system_content + human_content）

### 4.4 问题重写

- 有历史消息时使用 HISTORY_REWRITE_SYSTEM_PROMPT，输入包含对话历史摘要
- 无历史消息时使用 QUESTION_REWRITE_SYSTEM_PROMPT，独立重写
- 重写输出包含 completed_question（补全后的完整问题）和 rewritten_query（检索关键词）

### 4.5 回答分段

所有回答 prompt 的 final_answer 字段要求分段输出，用空行分隔不同要点。前端 simpleMarkdown 函数将双换行渲染为段落分隔。

---

## 5. 当前模型配置

| 用途 | 模型 | API 提供方 |
|------|------|-----------|
| 问题重写 + 分类 | gpt-3.5-turbo | fe8.cn |
| 查询向量化 | text-embedding-v4 | DashScope |
| 检索结果重排 | qwen3-rerank | DashScope |
| 生成最终回答 | gpt-4-turbo | fe8.cn |
