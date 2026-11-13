"""AnySearch 动态搜索客户端。

- 结果侧按域名白名单过滤（官方没有 site 参数，只能客户端筛）
- 结果缓存 24 小时，避免重复消耗配额（免费档约 1000 次/天）
- 无 Key 时不报错，返回空列表并由上层降级到静态知识库
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx

from app.core.errors import DependencyUnavailable

logger = logging.getLogger("campus.anysearch")


def _norm(query: str) -> str:
    return " ".join(query.split()).lower()


def query_hash(query: str, zone: str) -> str:
    return hashlib.sha256(f"{zone}:{_norm(query)}".encode()).hexdigest()


class AnySearchClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        zone: str = "cn",
        domain_suffix: str = "hntou.edu.cn",
        timeout: float = 12.0,
        max_results: int = 8,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._zone = zone
        self._suffix = domain_suffix
        self._timeout = timeout
        self._max = max_results

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    async def search(self, query: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base}/v1/search",
                    headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                    json={"query": query, "max_results": self._max, "zone": self._zone},
                )
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise DependencyUnavailable(f"搜索服务不可用：{exc.__class__.__name__}") from exc
        except ValueError as exc:
            raise DependencyUnavailable("搜索服务返回格式不正确") from exc

        raw = payload.get("results") or payload.get("data") or []
        items: list[dict[str, Any]] = []
        for item in raw:
            url = str(item.get("url") or "")
            if self._suffix and self._suffix not in url:
                continue  # 只保留校内来源
            items.append(
                {
                    "title": str(item.get("title") or "")[:120],
                    "url": url,
                    "content": str(item.get("content") or item.get("snippet") or "")[:800],
                }
            )
        return items[: self._max]

    @staticmethod
    def cache_key(query: str, zone: str = "cn") -> str:
        return query_hash(query, zone)

    @staticmethod
    def dumps(items: list[dict[str, Any]]) -> str:
        return json.dumps(items, ensure_ascii=False)
