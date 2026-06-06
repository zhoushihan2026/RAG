# API 契约 Spec

> 版本: v1 (单轮对话，无记忆)
> 生成日期: 2026-06-05
> 原则: 对齐 Streamlit 现有功能，不新增业务逻辑；预留多轮对话扩展点

---

## 概述

FastAPI 后端包装现有 `Pipeline` 类，提供 REST API 供 React 前端调用。

当前版本行为：每次提问独立，无上下文记忆。API 中预留 `session_id` 字段，但 v1 实现忽略历史消息。

---

## 1. 问答接口

### POST /api/chat

流式问答接口，对应 Streamlit 中的 `pipeline.answer_single_question_stream()`。

**请求:**

```json
{
  "question": "中芯国际2024年研发投入占营业收入的比例是多少？",
  "session_id": "optional-session-id"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | 是 | 用户问题，不能为空 |
| session_id | string | 否 | 会话ID，v1 忽略，每次提问独立处理 |

**响应: Server-Sent Events (SSE)**

Content-Type: `text/event-stream`

事件类型:

| 事件 type | content 类型 | 说明 |
|-----------|-------------|------|
| status | string | 状态提示（"正在识别公司名称..."等） |
| stream_start | string | 流式输出开始，content 为空 |
| token | string | 流式 token 片段 |
| done | object | 完成，content 为完整答案结构 |
| error | string | 错误信息 |

**done 事件的 content 结构:**

```json
{
  "final_answer": "2024年研发投入占营业收入比例约...",
  "step_by_step_analysis": "1. 问题询问...2. ...",
  "reasoning_summary": "从年报直接提取...",
  "relevant_pages": [5, 8],
  "source_files": {
    "abc123": {
      "file_name": "中芯国际2024年年度报告",
      "company_name": "中芯国际"
    }
  },
  "references": [
    {
      "pdf_sha1": "abc123",
      "page_index": 5,
      "source_file": "中芯国际2024年年度报告"
    }
  ]
}
```

**错误响应 (非流式):**

| HTTP 状态码 | 场景 |
|------------|------|
| 422 | question 为空或缺失（FastAPI Pydantic 验证） |
| 200 + error event | Pipeline 内部错误（SSE 流中返回 error 事件） |

---

## 2. 文件上传接口

### POST /api/upload

上传 PDF 文件到知识库，对应 Streamlit 中的 `pipeline.process_single_pdf_file()`。

**请求:** `multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | PDF 文件 |

**响应 (JSON):**

```json
{
  "status": "success",
  "message": "上传数据库成功",
  "file_name": "中芯国际2024年年度报告"
}
```

| status | 说明 |
|--------|------|
| success | 上传并处理成功 |
| exists | 文件已存在于数据库中 |
| error | 处理失败 |

**错误响应:**

| HTTP 状态码 | 场景 |
|------------|------|
| 400 | 文件非 PDF |
| 422 | 未提供文件（FastAPI File 必填验证） |
| 500 | 处理过程中出错 |

---

## 3. 知识库状态接口

### GET /api/kb/status

获取知识库当前状态（已入库的文件列表等）。

**响应 (JSON):**

```json
{
  "total_files": 5,
  "files": [
    {
      "sha1": "abc123",
      "file_name": "中芯国际2024年年度报告",
      "company_name": "中芯国际"
    }
  ]
}
```

数据来源: 读取 `databases/chunked_reports/*.json` 的 metainfo 字段，对应 Pipeline._get_source_file_names()。

---

## 4. 健康检查

### GET /api/health

**响应:**

```json
{
  "status": "ok"
}
```

---

## 5. SSE 事件流示例

```
event: status
data: {"type": "status", "content": "正在识别公司名称..."}

event: status
data: {"type": "status", "content": "正在重写问题并分析问题类型..."}

event: status
data: {"type": "status", "content": "正在检索 中芯国际 的相关文档..."}

event: status
data: {"type": "status", "content": "正在生成回答..."}

event: stream_start
data: {"type": "stream_start", "content": ""}

event: token
data: {"type": "token", "content": "2024"}

event: token
data: {"type": "token", "content": "年研发投入"}

...

event: done
data: {"type": "done", "content": {"final_answer": "...", "step_by_step_analysis": "...", ...}}
```

---

## 6. v1 行为约束

1. **无记忆**: 每次调用 `/api/chat` 独立处理，不读取也不写入会话历史
2. **session_id 忽略**: 传入 session_id 不报错，但不生效
3. **流式输出**: 必须使用 SSE，前端需要 EventSource 或 fetch + ReadableStream
4. **单文件上传**: 每次只上传一个 PDF
5. **Pipeline 初始化**: FastAPI 启动时初始化 Pipeline 实例，全局复用
6. **配置**: 使用 `hybrid_bm25_vector_config` 作为默认 RunConfig

---

## 7. v2 预留扩展点

以下字段和接口在 v1 中不实现，但 API 设计需预留:

- `session_id`: `/api/chat` 请求中已有此字段，v2 实现会话存储和历史注入
- `GET /api/sessions`: 获取会话列表
- `GET /api/sessions/{id}/messages`: 获取会话消息历史
- `DELETE /api/sessions/{id}`: 删除会话

---

## 8. CORS 配置

FastAPI 需配置 CORS 中间件，允许前端开发服务器访问:

- 允许来源: `http://localhost:5173` (Vite 默认端口)
- 允许方法: GET, POST, OPTIONS
- 允许头: Content-Type
- 允许凭证: true
