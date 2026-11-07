"""业务异常与错误码。

约定：抛出 AppError 子类，由全局异常处理器统一转成
    {code, message, data, trace_id}
HTTP 状态码与业务码同时表达语义，前端按 code 分支。
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    OK = 0
    BAD_REQUEST = 1001
    AUTH_REQUIRED = 2001
    FORBIDDEN = 2002
    NOT_FOUND = 3001
    VALIDATION_FAILED = 4001
    RATE_LIMITED = 5001
    DEPENDENCY_UNAVAILABLE = 6001
    INTERNAL = 9001


class AppError(Exception):
    code: int = ErrorCode.INTERNAL
    http_status: int = 500
    default_message: str = "服务器内部错误"

    def __init__(self, message: str | None = None, *, data: Any = None) -> None:
        self.message = message or self.default_message
        self.data = data
        super().__init__(self.message)


class BadRequest(AppError):
    code = ErrorCode.BAD_REQUEST
    http_status = 400
    default_message = "请求参数不正确"


class AuthRequired(AppError):
    code = ErrorCode.AUTH_REQUIRED
    http_status = 401
    default_message = "请先登录"


class TokenExpired(AuthRequired):
    default_message = "登录已过期，请重新登录"


class Forbidden(AppError):
    code = ErrorCode.FORBIDDEN
    http_status = 403
    default_message = "没有权限执行该操作"


class NotFound(AppError):
    code = ErrorCode.NOT_FOUND
    http_status = 404
    default_message = "资源不存在"


class ValidationFailed(AppError):
    code = ErrorCode.VALIDATION_FAILED
    http_status = 422
    default_message = "数据校验失败"


class RateLimited(AppError):
    code = ErrorCode.RATE_LIMITED
    http_status = 429
    default_message = "操作太频繁，请稍后再试"


class DependencyUnavailable(AppError):
    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    http_status = 503
    default_message = "依赖服务暂不可用"


# 便于日志与前端识别的细分依赖
class ModelUnavailable(DependencyUnavailable):
    default_message = "模型服务暂不可用，请稍后再试"


class EduUnavailable(DependencyUnavailable):
    default_message = "教务系统暂时无法访问，请稍后再试"


class SearchUnavailable(DependencyUnavailable):
    default_message = "搜索服务暂不可用，已改用站内知识库"
