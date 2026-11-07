"""知识库业务：上传、列表、切片查看、删除、重建。

没有引入任务队列（选型冻结）：解析用 asyncio 后台任务 + 信号量串行执行。
代价：进程重启会丢失"进行中"的任务，重启后需在管理端触发重建 —— 已在部署手册写明。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError, NotFound, ValidationFailed
from app.rag.indexer import Indexer
from app.rag.parser import SUPPORTED_SUFFIXES
from app.rag.store import VectorStore
from app.repositories.kb import KbRepository

logger = logging.getLogger("campus.kb")


class KbService:
    def __init__(
        self,
        *,
        settings: Settings,
        repo: KbRepository,
        indexer: Indexer,
        store: VectorStore,
        upload_dir: Path,
    ) -> None:
        self._settings = settings
        self._repo = repo
        self._indexer = indexer
        self._store = store
        self._upload_dir = upload_dir
        self._semaphore = asyncio.Semaphore(1)  # 单进程串行解析，避免 CPU/显存争抢
        self._running: set[asyncio.Task] = set()

    # ---------- 上传 ----------
    async def upload(
        self,
        *,
        filename: str,
        content: bytes,
        uploaded_by: int | None,
        source_dept: str | None = None,
        effective_from: date | None = None,
        effective_to: date | None = None,
    ) -> dict[str, Any]:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValidationFailed(f"不支持的文件类型：{suffix or '未知'}")
        if not content:
            raise ValidationFailed("文件内容为空")
        limit = self._settings.upload_max_mb * 1024 * 1024
        if len(content) > limit:
            raise ValidationFailed(f"文件超过 {self._settings.upload_max_mb}MB 限制")

        file_hash = hashlib.sha256(content).hexdigest()
        existing = await self._repo.find_by_hash(file_hash)
        if existing:
            raise ValidationFailed(f"内容相同的文件已存在：{existing['filename']}（id={existing['id']}）")

        await asyncio.to_thread(self._upload_dir.mkdir, parents=True, exist_ok=True)
        stored_path = self._upload_dir / f"{file_hash}{suffix}"
        await asyncio.to_thread(stored_path.write_bytes, content)

        file_id = await self._repo.create_file(
            filename=filename,
            file_hash=file_hash,
            file_type=suffix.lstrip("."),
            size_bytes=len(content),
            source_dept=source_dept,
            effective_from=effective_from.isoformat() if effective_from else None,
            effective_to=effective_to.isoformat() if effective_to else None,
            uploaded_by=uploaded_by,
        )
        task_id = await self._repo.add_task(file_id, stage="pipeline")
        self._spawn(self._run_index(file_id=file_id, task_id=task_id, path=stored_path))

        record = await self._repo.get_file(file_id)
        assert record is not None
        return record

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def _run_index(self, *, file_id: int, task_id: int, path: Path) -> None:
        async with self._semaphore:
            await self._repo.start_task(task_id)
            await self._repo.update_status(file_id, status="parsing")
            record = await self._repo.get_file(file_id)
            source_meta = {
                "source_dept": (record or {}).get("source_dept") or "",
                "filename": (record or {}).get("filename") or path.name,
            }
            try:
                result = await self._indexer.index_file(
                    file_id=file_id, path=path, source_meta=source_meta
                )
                await self._repo.update_status(
                    file_id,
                    status="success",
                    channel=result.channel,
                    chunk_count=result.chunk_count,
                )
                await self._repo.finish_task(task_id, status="success")
            except AppError as exc:
                await self._repo.update_status(file_id, status="failed")
                await self._repo.finish_task(task_id, status="failed", error=exc.message)
                logger.warning("index_failed", extra={"extra_fields": {"file_id": file_id, "error": exc.message}})
            except Exception as exc:  # noqa: BLE001 - 后台任务不能把异常抛给事件循环
                await self._repo.update_status(file_id, status="failed")
                await self._repo.finish_task(task_id, status="failed", error=str(exc)[:500])
                logger.exception("index_crashed", extra={"extra_fields": {"file_id": file_id}})

    # ---------- 查询 ----------
    async def list_files(self, *, page: int, size: int, status: str | None) -> dict[str, Any]:
        items, total = await self._repo.list_files(page=page, size=size, status=status)
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_file(self, file_id: int) -> dict[str, Any]:
        record = await self._repo.get_file(file_id)
        if record is None or record.get("deleted_at"):
            raise NotFound("文件不存在")
        return record

    async def list_chunks(self, *, file_id: int, page: int, size: int) -> dict[str, Any]:
        await self.get_file(file_id)
        items, total = await self._repo.list_chunks(file_id=file_id, page=page, size=size)
        return {"items": items, "total": total, "page": page, "size": size}

    # ---------- 变更 ----------
    async def delete(self, file_id: int) -> None:
        await self.get_file(file_id)
        await asyncio.to_thread(self._store.delete_by_file, file_id)
        await self._repo.replace_chunks(file_id, [])
        if not await self._repo.soft_delete(file_id):
            raise NotFound("文件不存在")

    async def reindex(self, file_id: int) -> dict[str, Any]:
        record = await self.get_file(file_id)
        suffix = "." + str(record["file_type"])
        path = self._upload_dir / f"{record['file_hash']}{suffix}"
        if not path.exists():
            raise NotFound("原始文件已不在服务器上，请重新上传")
        await asyncio.to_thread(self._store.delete_by_file, file_id)
        await self._repo.update_status(file_id, status="pending")
        task_id = await self._repo.add_task(file_id, stage="pipeline")
        self._spawn(self._run_index(file_id=file_id, task_id=task_id, path=path))
        return await self.get_file(file_id)
