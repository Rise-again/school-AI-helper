"""vLLM 客户端（OpenAI 兼容）。

- 非流式：意图分类、查询改写这类短调用
- 流式：对话生成，逐 token 产出
- 模型不可用时抛 ModelUnavailable，由上层降级为话术而不是 500
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from app.core.errors import ModelUnavailable

logger = logging.getLogger("campus.llm")


class LLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "EMPTY",
        timeout: float = 60.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._model = model
        self._key = api_key
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"}

    def _payload(self, messages: list[dict], *, temperature: float, max_tokens: int, stream: bool) -> dict:
        return {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        max_tokens: int = 256,
    ) -> str:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(messages, temperature=temperature, max_tokens=max_tokens, stream=False),
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"模型调用失败：{exc.__class__.__name__}") from exc
        except ValueError as exc:
            raise ModelUnavailable("模型返回格式不正确") from exc
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelUnavailable("模型返回结构异常") from exc

    async def stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.3,
        max_tokens: int = 800,
    ) -> AsyncIterator[str]:
        """逐块产出文本增量。连接异常时抛 ModelUnavailable（已产出的内容由调用方保留）。"""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._base}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(messages, temperature=temperature, max_tokens=max_tokens, stream=True),
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            payload = json.loads(chunk)
                        except ValueError:
                            continue
                        choices = payload.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        text = delta.get("content")
                        if text:
                            yield text
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"模型流式调用失败：{exc.__class__.__name__}") from exc
