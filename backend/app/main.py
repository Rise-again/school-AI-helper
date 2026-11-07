"""应用入口。

启动方式（必须带 --factory，因为配置在启动时才校验）：
    uvicorn app.main:create_app --factory --app-dir backend --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import envelope
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import log_fields, new_trace_id, setup_logging, trace_id_var
from app.db.pool import Database
from app.rag.embedding import HttpEmbeddingClient
from app.rag.indexer import Indexer
from app.rag.ocr import HttpOcrClient
from app.rag.parser import DocumentParser
from app.rag.store import ChromaVectorStore, UnavailableVectorStore, VectorStore
from app.repositories.conversations import ConversationRepository
from app.repositories.kb import KbRepository
from app.repositories.users import UserRepository
from app.services.auth_service import AuthService
from app.services.conversation_service import ConversationService
from app.services.kb_service import KbService

logger = logging.getLogger("campus")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    setup_logging(settings.log_level)

    db = Database(settings)
    try:
        await db.connect()
    except Exception as exc:  # noqa: BLE001 - 库没起也让服务起来，靠 /readyz 暴露
        logger.error("mysql_connect_failed", extra=log_fields(error=f"{exc.__class__.__name__}: {exc}"))

    app.state.db = db
    app.state.auth_service = AuthService(settings, UserRepository(db))
    app.state.conversation_service = ConversationService(ConversationRepository(db))

    kb_repo = KbRepository(db)
    try:
        vector_store: VectorStore = await asyncio.to_thread(
            ChromaVectorStore, settings.chroma_dir, settings.chroma_collection
        )
    except Exception as exc:  # noqa: BLE001 - chromadb 缺失/损坏不应导致整个服务起不来
        logger.error("vector_store_unavailable", extra=log_fields(error=str(exc)[:300]))
        vector_store = UnavailableVectorStore(str(exc)[:300])

    indexer = Indexer(
        parser=DocumentParser(
            HttpOcrClient(settings.ocr_base_url),
            pdf_mode=settings.parse_pdf_mode,
            min_chars=settings.ocr_min_chars,
        ),
        embedder=HttpEmbeddingClient(settings.embed_base_url, batch_size=settings.embed_batch_size),
        store=vector_store,
        repo=kb_repo,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    app.state.kb_service = KbService(
        settings=settings,
        repo=kb_repo,
        indexer=indexer,
        store=vector_store,
        upload_dir=settings.upload_dir,
    )

    logger.info("service_started", extra=log_fields(env=settings.app_env, db_connected=db.connected))
    try:
        yield
    finally:
        await db.close()
        logger.info("service_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="校园智能助手 API",
        version="0.1.0",
        description="三角色校园问答与教务服务。响应统一为 {code, message, data, trace_id}。",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id"],
    )

    # ---------- 中间件：trace_id + 访问日志 ----------
    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        incoming = request.headers.get("X-Trace-Id", "").strip()
        trace_id = incoming[:32] if incoming else new_trace_id()
        token = trace_id_var.set(trace_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra=log_fields(method=request.method, path=request.url.path),
            )
            trace_id_var.reset(token)
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Trace-Id"] = trace_id
        if request.url.path not in ("/healthz",):
            logger.info(
                "request",
                extra=log_fields(
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    ms=round(elapsed_ms, 1),
                ),
            )
        trace_id_var.reset(token)
        return response

    # ---------- 异常处理 ----------
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.error("app_error", extra=log_fields(code=exc.code, msg=exc.message))
        return JSONResponse(
            status_code=exc.http_status,
            content=envelope(exc.code, exc.message, exc.data),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": ".".join(str(part) for part in err["loc"]), "msg": err["msg"], "type": err["type"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=envelope(ErrorCode.VALIDATION_FAILED, "参数校验失败", details),
        )

    _HTTP_CODE_MAP = {
        400: ErrorCode.BAD_REQUEST,
        401: ErrorCode.AUTH_REQUIRED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        405: ErrorCode.BAD_REQUEST,
        429: ErrorCode.RATE_LIMITED,
    }

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 让 404/405 这类框架级错误也走统一信封，前端只需处理一种结构
        code = _HTTP_CODE_MAP.get(exc.status_code, ErrorCode.INTERNAL if exc.status_code >= 500 else ErrorCode.BAD_REQUEST)
        message = exc.detail if isinstance(exc.detail, str) else "请求无法处理"
        return JSONResponse(status_code=exc.status_code, content=envelope(code, message, None))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra=log_fields(path=request.url.path))
        return JSONResponse(
            status_code=500,
            content=envelope(ErrorCode.INTERNAL, "服务器内部错误，请稍后重试"),
        )

    app.include_router(api_router)

    # ---------- 探针 ----------
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz(request: Request) -> JSONResponse:
        db: Database = request.app.state.db
        mysql_ok = await db.ping()
        body = {
            "status": "ok" if mysql_ok else "degraded",
            "components": {
                "mysql": "ok" if mysql_ok else (db.last_error or "down"),
                "models": "pending",  # P2 起接入 model-service /healthz
            },
        }
        return JSONResponse(status_code=200 if mysql_ok else 503, content=body)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"name": "校园智能助手 API", "docs": "/docs", "health": "/healthz"}

    return app
