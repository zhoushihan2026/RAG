"""
FastAPI 应用主模块
包装 Pipeline 类，提供 REST API 供前端调用
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.pipeline import Pipeline, hybrid_bm25_vector_config


# ============================================================
# 请求/响应模型
# ============================================================

class ChatRequest(BaseModel):
    """问答请求"""
    question: str = Field(..., min_length=1, description="用户问题")
    session_id: Optional[str] = Field(None, description="会话ID，v1 忽略")


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
            "http://localhost:5178",
            "http://127.0.0.1:5178",
            "http://localhost:5180",
            "http://127.0.0.1:5180",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # 如果未传入 pipeline，使用默认配置初始化
    if pipeline is None:
        root_path = Path(os.getenv("RAG_DATA_PATH", "data/stock_data"))
        pipeline = Pipeline(root_path, run_config=hybrid_bm25_vector_config)

    # 将 pipeline 存储在 app.state 中
    app.state.pipeline = pipeline

    # ============================================================
    # 路由
    # ============================================================

    @app.get("/api/health", response_model=HealthResponse)
    async def health_check():
        """健康检查"""
        return HealthResponse(status="ok")

    @app.post("/api/chat")
    async def chat(request: ChatRequest):
        """
        流式问答接口
        返回 SSE 事件流
        """
        pipeline = app.state.pipeline

        def event_generator():
            try:
                for event in pipeline.answer_single_question_stream(
                    request.question, kind="string"
                ):
                    event_type = event.get("type", "status")
                    event_content = event.get("content", "")

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

    return app


# 默认应用实例（uvicorn 运行时使用）
app = create_app()
