"""教务系统适配层：整个项目里唯一 import school-sdk 的地方。

约定：
- 业务层只认 EduClient 协议与 EduError 家族，不感知 SDK 类型；
- SDK 是同步的 requests 实现，服务层用 asyncio.to_thread 包一层；
- 口令只在 login 时传入，不缓存明文、不写日志；
- 会话对象（UserClient）常驻内存，失效时由服务层重新登录一次。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from app.core.logging import log_fields
import logging
import socket

if TYPE_CHECKING:  # 仅用于类型，运行时不需要 pydantic（本地验证脚本可单独跑）
    from app.core.config import Settings

logger = logging.getLogger("campus.edu")


class EduError(Exception):
    """教务系统相关错误的基类。"""


class EduAuthError(EduError):
    """账号或口令不正确（偏用户侧）。"""


class EduSessionExpired(EduError):
    """会话失效，可重登一次再试。"""


class EduUnavailable(EduError):
    """网络不通、上游异常、SDK 缺失等（偏环境侧）。"""


@dataclass
class EduSession:
    """一次成功登录后的会话句柄。raw 是 SDK 的 UserClient。"""

    account: str
    raw: Any


class EduClient(Protocol):
    def login(self, account: str, password: str) -> EduSession: ...

    def info(self, session: EduSession) -> dict[str, Any]: ...

    def schedule(self, session: EduSession, year: int, term: int) -> dict[str, Any]: ...

    def scores(self, session: EduSession, year: int, term: int) -> dict[str, Any]: ...


def _endpoints_with_base(base_path: str) -> dict[str, Any]:
    from school_sdk.config import URL_ENDPOINT

    def fix(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: fix(v) for k, v in value.items()}
        if isinstance(value, str) and value.startswith("/"):
            return f"{base_path}{value}"
        return value

    return {k: fix(v) for k, v in URL_ENDPOINT.items()}


class SchoolSdkEduClient:
    """基于 school-sdk 1.9.x 的实现（本地打过补丁：去掉无用的 ast.Bytes 导入）。"""

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        # 端点表依赖 school-sdk；延迟到真正登录时再构造，避免没装 SDK 时应用起不来
        self._endpoints: dict[str, Any] | None = None

    def _endpoints_config(self) -> dict[str, Any]:
        if self._endpoints is None:
            self._endpoints = _endpoints_with_base(self._settings.edu_base_path)
        return self._endpoints

    def _preflight(self) -> None:
        """先做一次带超时的 TCP 连接：SDK 自己没用 timeout 参数，
        上游被防火墙静默丢包时会卡在系统级 connect（约 2 分钟），必须自己兜。"""
        timeout = max(1.0, min(5.0, float(self._settings.edu_timeout_s)))
        try:
            with socket.create_connection(
                (self._settings.edu_host, self._settings.edu_port), timeout=timeout
            ):
                return
        except OSError as exc:
            raise EduUnavailable(
                f"无法连接教务系统（{self._settings.edu_host}:{self._settings.edu_port}）"
            ) from exc

    # -------- 内部 --------
    def _build_client(self):
        try:
            from school_sdk import SchoolClient
        except ImportError as exc:  # 依赖没装/装错环境
            raise EduUnavailable(f"school-sdk 未安装：{exc}") from exc
        return SchoolClient(
            host=self._settings.edu_host,
            port=self._settings.edu_port,
            ssl=self._settings.edu_ssl,
            exist_verify=False,
            retry=self._settings.edu_retry,
            timeout=self._settings.edu_timeout_s,
            url_endpoints=self._endpoints_config(),
        )

    @staticmethod
    def _translate(exc: Exception, action: str) -> EduError:
        """把 SDK / requests 的异常翻译成业务错误，避免把栈和 URL 抛给前端。"""
        name = type(exc).__name__
        message = str(exc)
        if name in {"LoginException", "RTKException"}:
            if "重新登录" in message or "session" in message.lower():
                return EduSessionExpired(f"{action}时会话已失效")
            return EduAuthError("教务账号或密码不正确")
        # requests 的各种连接问题、SDK 的解析问题都算上游不可用
        logger.warning("edu_upstream_error", extra=log_fields(action=action, error=f"{name}: {message[:200]}"))
        return EduUnavailable("教务系统暂时无法访问")

    # -------- 协议实现 --------
    def login(self, account: str, password: str) -> EduSession:
        self._preflight()
        client = self._build_client()
        try:
            user = client.user_login(account, password)
        except Exception as exc:  # noqa: BLE001 - 统一翻译
            raise self._translate(exc, "登录") from exc
        return EduSession(account=account, raw=user)

    def info(self, session: EduSession) -> dict[str, Any]:
        self._preflight()
        try:
            data = session.raw.get_info()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, "读取个人信息") from exc
        return data if isinstance(data, dict) else {}

    def schedule(self, session: EduSession, year: int, term: int) -> dict[str, Any]:
        self._preflight()
        try:
            data = session.raw.get_schedule(year=year, term=term)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, "查询课表") from exc
        return data if isinstance(data, dict) else {}

    def scores(self, session: EduSession, year: int, term: int) -> dict[str, Any]:
        self._preflight()
        try:
            data = session.raw.get_score(year=year, term=term)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, "查询成绩") from exc
        return data if isinstance(data, dict) else {}
