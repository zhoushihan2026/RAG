"""
FastAPI 应用主模块
包装 Pipeline 类，提供 REST API 供前端调用
"""
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.pipeline import Pipeline, hybrid_bm25_vector_config
from src.session_manager import SessionManager


# ============================================================
# 请求/响应模型
# ============================================================

class ChatRequest(BaseModel):
    """问答请求"""
    question: str = Field(..., min_length=1, description="用户问题")
    session_id: Optional[str] = Field(None, description="会话ID")


class RenameSessionRequest(BaseModel):
    """重命名会话请求"""
    title: str = Field(..., min_length=1, description="新标题")


class UploadResponse(BaseModel):
    """上传响应"""
    status: str
    message: str
    file_name: str = ""


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str


class KBFileItem(BaseModel):
    """知识库文件条目"""
    sha1: str
    file_name: str
    company_name: str


class KBStatusResponse(BaseModel):
    """知识库状态响应"""
    total_files: int
    files: list[KBFileItem]


# ============================================================
# 应用工厂
# ============================================================

def create_app(pipeline: Pipeline = None) -> FastAPI:
    """创建 FastAPI 应用实例"""
    app = FastAPI(title="RAG 企业知识库问答系统 API", version="1.0.0")

    # CORS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:5178",
            "http://127.0.0.1:5178",
            "http://localhost:5180",
            "http://127.0.0.1:5180",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS", "DELETE", "PATCH"],
        allow_headers=["Content-Type"],
    )

    # 如果未传入 pipeline，使用默认配置初始化
    if pipeline is None:
        root_path = Path(os.getenv("RAG_DATA_PATH", "data/stock_data"))
        pipeline = Pipeline(root_path, run_config=hybrid_bm25_vector_config)

    # 将 pipeline 存储在 app.state 中
    app.state.pipeline = pipeline

    # v2: 初始化 SessionManager
    app.state.session_manager = SessionManager()

    # 全局异常处理器：确保所有错误都返回 JSON 而非 500 HTML
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        import traceback
        traceback.print_exc()
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"detail": f"服务器内部错误: {str(exc)}"},
        )

    # ============================================================
    # 路由
    # ============================================================

    @app.get("/")
    async def root():
        """根路径，返回 API 基本信息"""
        return {"status": "ok", "message": "RAG Knowledge Base API", "docs": "/docs"}

    @app.get("/api/health", response_model=HealthResponse)
    async def health_check():
        """健康检查"""
        return HealthResponse(status="ok")

    @app.post("/api/chat")
    async def chat(request: ChatRequest):
        """
        流式问答接口
        返回 SSE 事件流
        v2: 支持 session_id，自动管理对话历史
        """
        pipeline = app.state.pipeline
        session_manager = app.state.session_manager

        # v2: session_id 处理
        session_id = request.session_id
        if not session_id:
            session_id = str(uuid.uuid4())

        # v2: 检查会话是否达到上限
        session = session_manager.get_or_create(session_id)
        if session.count_user_messages() >= session_manager.max_user_messages:
            def error_generator():
                yield f"event: error\ndata: {json.dumps({'error': '此对话已达上限（50条），请新建对话'}, ensure_ascii=False)}\n\n"
            return StreamingResponse(error_generator(), media_type="text/event-stream")

        # v2: 获取历史消息
        history_messages = session_manager.get_history_messages(session_id)

        # v2: 保存用户问题到会话
        session_manager.add_message(session_id, "user", request.question)

        def event_generator():
            final_answer = ""
            try:
                for event in pipeline.answer_single_question_stream(
                    request.question, kind="string",
                    history_messages=history_messages,
                ):
                    event_type = event.get("type", "status")
                    event_content = event.get("content", "")

                    # 收集最终答案（用于保存到会话）
                    if event_type == "done" and isinstance(event_content, dict):
                        final_answer = event_content.get("final_answer", "")
                        # 回退：如果 final_answer 为空，使用 step_by_step_analysis
                        if not final_answer:
                            final_answer = event_content.get("step_by_step_analysis", "")

                    if event_type == "done":
                        # done 事件的 content 是 dict，序列化为 JSON
                        content_str = json.dumps(event_content, ensure_ascii=False)
                    elif isinstance(event_content, dict):
                        content_str = json.dumps(event_content, ensure_ascii=False)
                    else:
                        content_str = str(event_content)

                    # SSE 格式: event: xxx\ndata: xxx\n\n
                    sse_event = f"event: {event_type}\ndata: {content_str}\n\n"
                    yield sse_event

            except Exception as e:
                error_event = f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
                yield error_event
            finally:
                # v2: 保存助手回答到会话
                session_manager.add_message(
                    session_id, "assistant",
                    final_answer or "回答生成失败",
                    metadata={"company_name": "", "question_category": ""}
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/upload", response_model=UploadResponse)
    async def upload_file(file: UploadFile = File(...)):
        """
        上传 PDF 文件到知识库
        """
        # 检查文件类型
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

        pipeline = app.state.pipeline

        # 保存到临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = pipeline.process_single_pdf_file(
                tmp_path, original_filename=file.filename
            )
            return UploadResponse(
                status=result.get("status", "unknown"),
                message=result.get("message", ""),
                file_name=result.get("file_name", ""),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    @app.get("/api/kb/status", response_model=KBStatusResponse)
    async def kb_status():
        """
        获取知识库状态
        """
        pipeline = app.state.pipeline
        source_files = pipeline._get_source_file_names()

        files = [
            KBFileItem(
                sha1=sha1,
                file_name=info.get("file_name", ""),
                company_name=info.get("company_name", ""),
            )
            for sha1, info in source_files.items()
        ]

        return KBStatusResponse(total_files=len(files), files=files)

    # ============================================================
    # v2: 会话管理路由
    # ============================================================

    @app.get("/api/sessions")
    async def list_sessions():
        """获取会话列表"""
        return {"sessions": app.state.session_manager.list_sessions()}

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        """获取会话详情"""
        detail = app.state.session_manager.get_session_detail(session_id)
        if not detail:
            raise HTTPException(status_code=404, detail="会话不存在")
        return detail

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        """删除会话"""
        app.state.session_manager.delete_session(session_id)
        return {"status": "deleted"}

    @app.patch("/api/sessions/{session_id}")
    async def rename_session(session_id: str, request: RenameSessionRequest):
        """重命名会话"""
        session = app.state.session_manager.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        app.state.session_manager.rename_session(session_id, request.title)
        return {
            "id": session_id,
            "title": request.title,
            "updated_at": session.updated_at.isoformat() + "Z",
        }

    return app


# 默认应用实例（uvicorn 运行时使用）
app = create_app()
