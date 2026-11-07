"""结构化日志与 trace_id。

- 全链路一个 trace_id：中间件生成 → 业务日志 → 模型调用 → 落库。
- 日志为单行 JSON，方便 grep / 采集；同时做敏感字段脱敏。
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")

_SENSITIVE_HINTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "credential",
    "cipher",
    "api_key",
    "apikey",
)

MASK = "******"


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in _SENSITIVE_HINTS)


def mask(value: Any, *, depth: int = 0) -> Any:
    """递归脱敏：字典按 key 判断，列表逐项处理。"""
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {
            k: (MASK if is_sensitive(str(k)) else mask(v, depth=depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [mask(v, depth=depth + 1) for v in value[:20]]
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "..."
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": trace_id_var.get(),
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(mask(extra))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)
    # 第三方库降噪：连接池与 ASGI 的 DEBUG 会淹没有效信息
    for noisy in ("aiomysql", "asyncio", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))


def log_fields(**fields: Any) -> dict[str, Any]:
    """用法：logger.info("...", extra=log_fields(user_id=1))"""
    return {"extra_fields": fields}
