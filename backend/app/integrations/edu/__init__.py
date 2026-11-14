"""教务系统集成。业务代码从 `client` 导入协议与异常，不直接依赖 SDK。"""

from app.integrations.edu.client import (
    EduAuthError,
    EduClient,
    EduError,
    EduSession,
    EduSessionExpired,
    EduUnavailable,
    SchoolSdkEduClient,
)

__all__ = [
    "EduAuthError",
    "EduClient",
    "EduError",
    "EduSession",
    "EduSessionExpired",
    "EduUnavailable",
    "SchoolSdkEduClient",
]
