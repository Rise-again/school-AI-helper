"""客户端来源与共享网关判断。

背景（2026-11-15 实测）
- 平台自定义服务经反向代理进来后，ASGI 看到的客户端地址统一是 Docker 网关
  `172.17.0.1`，真实访客 IP 拿不到；
- 平台还会原样透传客户端自带的 `X-Forwarded-For`，实测伪造 `9.9.9.9` 会被
  Uvicorn 当成来源地址，因此**不能**用 XFF 做限流依据。

结论
- 访客限流用浏览器 cookie（`visitor_id`）做主键；
- IP 维度只在来源不是共享网关时启用，作为以后换到真实反向代理后的兜底。
"""

from __future__ import annotations

_SHARED_PREFIXES = ("172.17.", "127.", "::1", "10.", "192.168.")


def is_shared_gateway(ip: str | None) -> bool:
    """来自容器网关/本机回环/内网的地址不能代表单个访客。"""
    if not ip or ip == "unknown":
        return True
    return ip.startswith(_SHARED_PREFIXES)
