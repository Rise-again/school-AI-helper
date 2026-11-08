"""云端模型服务。

只在内网监听（默认 127.0.0.1:8002），对外不可见；后端通过 HTTP 调用。
端点契约与 backend/app/rag/{embedding,ocr}.py 一致。

启动：
    uvicorn app:create_app --factory --host 127.0.0.1 --port 8002
环境变量：
    BGE_EMBED_PATH / BGE_RERANK_PATH / MODEL_DEVICE / MODEL_API_KEY
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backends import LocalBackend, ModelBackend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("model-service")

MAX_EMBED_BATCH = 128
MAX_RERANK_PASSAGES = 64


class EmbedRequest(BaseModel):
    input: list[str] = Field(min_length=1, max_length=MAX_EMBED_BATCH)
    model: str | None = None


class RerankRequest(BaseModel):
    query: str = Field(min_length=1)
    passages: list[str] = Field(min_length=1, max_length=MAX_RERANK_PASSAGES)
    top_k: int | None = Field(default=None, ge=1)
    return_documents: bool = False
    model: str | None = None


def create_app(backend: ModelBackend | None = None, *, api_key: str | None = None) -> FastAPI:
    key = api_key if api_key is not None else os.getenv("MODEL_API_KEY", "")
    engine: ModelBackend = backend or LocalBackend(
        embed_path=os.getenv("BGE_EMBED_PATH", ""),
        rerank_path=os.getenv("BGE_RERANK_PATH", ""),
        device=os.getenv("MODEL_DEVICE", "cuda"),
    )

    app = FastAPI(title="校园智能助手 · 模型服务", version="0.1.0")
    app.state.engine = engine

    def auth(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> None:
        if not key:
            return  # 未配置密钥时不校验（仅限本地/内网）
        token = ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        elif x_api_key:
            token = x_api_key.strip()
        if token != key:
            raise HTTPException(status_code=401, detail="模型服务密钥不正确")

    @app.get("/healthz")
    def healthz() -> dict:
        status = engine.status()
        ready = all(v == "loaded" for v in status.values())
        return {"status": "ok" if ready else "partial", "models": status, "dim": engine.dim}

    @app.post("/v1/embeddings", dependencies=[Depends(auth)])
    def embeddings(payload: EmbedRequest) -> dict:
        texts = [t for t in payload.input if t and t.strip()]
        if not texts:
            raise HTTPException(status_code=400, detail="input 不能为空")
        vectors = engine.embed(texts)
        return {
            "object": "list",
            "model": payload.model or "bge-large-zh-v1.5",
            "data": [
                {"object": "embedding", "index": i, "embedding": vec}
                for i, vec in enumerate(vectors)
            ],
            "usage": {"prompt_tokens": sum(len(t) for t in texts), "total_tokens": sum(len(t) for t in texts)},
        }

    @app.post("/v1/rerank", dependencies=[Depends(auth)])
    def rerank(payload: RerankRequest) -> dict:
        scores = engine.rerank(payload.query, payload.passages)
        if len(scores) != len(payload.passages):
            raise HTTPException(status_code=500, detail="重排返回数量与候选数不一致")
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        if payload.top_k:
            ranked = ranked[: payload.top_k]
        results = []
        for idx in ranked:
            item = {"index": idx, "relevance_score": scores[idx]}
            if payload.return_documents:
                item["document"] = {"text": payload.passages[idx]}
            results.append(item)
        return {"model": payload.model or "bge-reranker-v2-m3", "results": results}

    @app.post("/v1/ocr", dependencies=[Depends(auth)])
    async def ocr(file: UploadFile = File(...), pages: str | None = Form(default=None)) -> dict:
        suffix = Path(file.filename or "upload").suffix or ".png"
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="文件为空")

        wanted: list[int] | None = None
        if pages:
            try:
                wanted = [int(p) for p in pages.split(",") if p.strip()]
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="pages 需为逗号分隔的页码") from exc

        tmp = Path(tempfile.mkstemp(suffix=suffix)[1])
        try:
            tmp.write_bytes(raw)
            texts = engine.ocr(tmp, wanted)
        finally:
            tmp.unlink(missing_ok=True)

        return {
            "pages": [{"page_no": no, "text": text} for no, text in sorted(texts.items())],
            "text": "\n".join(text for _, text in sorted(texts.items())),
        }

    return app
