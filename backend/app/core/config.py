"""全局配置：启动即校验，缺项或占位值直接让服务起不来。

设计要点
- 只依赖 pydantic（选型内），不引入 pydantic-settings / python-dotenv。
- 优先级：进程环境变量 > backend/.env > 代码默认值。
- 本地零模型依赖：所有模型地址都是 HTTP 端点，模型在哪对业务层不可见。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_ENV_FILE = BACKEND_DIR / ".env"

_PLACEHOLDER_SECRETS = {
    "",
    "secret",
    "change-me",
    "changeme",
    "请替换为至少32位的随机字符串",
}


def _load_env_file(path: Path) -> dict[str, str]:
    """极简 .env 解析：KEY=VALUE，支持 # 注释与成对引号，不引入额外依赖。"""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


class Settings(BaseModel):
    model_config = ConfigDict(
        alias_generator=str.upper,
        populate_by_name=True,
        extra="forbid",
    )

    # 运行
    app_env: Literal["dev", "test", "prod"] = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # MySQL
    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_user: str
    mysql_password: str
    mysql_db: str = "campus_assistant"
    mysql_pool_min: int = Field(default=1, ge=1)
    mysql_pool_max: int = Field(default=10, ge=1)

    # 鉴权
    jwt_secret: str = Field(min_length=32)
    jwt_alg: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_expire_minutes: int = Field(default=720, ge=5)
    jwt_refresh_expire_days: int = Field(default=7, ge=1)

    # 大模型（云端 vLLM）
    llm_base_url: str
    llm_model: str = "qwen2.5-7b-instruct"
    llm_api_key: str = "EMPTY"
    llm_timeout_s: float = Field(default=60.0, gt=0)

    # 功能模型（云端 model-service）
    embed_base_url: str
    rerank_base_url: str
    ocr_base_url: str

    # 检索
    chroma_dir: Path = PROJECT_ROOT / "data" / "chroma"
    rag_top_k: int = Field(default=20, ge=1, le=200)
    rag_top_n: int = Field(default=5, ge=1, le=50)
    rag_score_threshold: float = Field(default=0.35, ge=0.0, le=1.0)

    # 数据获取
    anysearch_base_url: str = "https://api.anysearch.com"
    anysearch_api_key: str = ""
    anysearch_zone: Literal["cn", "intl"] = "cn"
    anysearch_daily_quota: int = Field(default=900, ge=1)
    edu_host: str = "zfjw.hntou.edu.cn"
    edu_port: int = Field(default=80, ge=1, le=65535)
    edu_ssl: bool = False
    edu_timeout_s: float = Field(default=10.0, gt=0)
    edu_retry: int = Field(default=2, ge=0, le=5)

    # 限流与队列（单 worker 内存实现）
    rate_limit_per_minute: int = Field(default=20, ge=1)
    queue_max_size: int = Field(default=50, ge=1)
    queue_max_wait_s: float = Field(default=30.0, ge=0)

    # 上传
    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"
    upload_max_mb: int = Field(default=50, ge=1, le=500)

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        if self.jwt_secret in _PLACEHOLDER_SECRETS:
            raise ValueError("JWT_SECRET 仍是占位值，请换成至少 32 位随机字符串")
        if self.rag_top_n > self.rag_top_k:
            raise ValueError("RAG_TOP_N 不能大于 RAG_TOP_K")
        if self.mysql_pool_min > self.mysql_pool_max:
            raise ValueError("MYSQL_POOL_MIN 不能大于 MYSQL_POOL_MAX")
        for name in ("llm_base_url", "embed_base_url", "rerank_base_url", "ocr_base_url"):
            if not getattr(self, name).startswith(("http://", "https://")):
                raise ValueError(f"{name.upper()} 必须是 http(s) 地址，当前为 {getattr(self, name)!r}")
        if self.app_env == "prod" and self.jwt_expire_minutes > 1440:
            raise ValueError("生产环境 JWT_EXPIRE_MINUTES 不应超过 1440")
        return self

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def llm_chat_url(self) -> str:
        return f"{self.llm_base_url.rstrip('/')}/chat/completions"

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        environ: dict[str, str] | None = None,
    ) -> "Settings":
        allowed = {name.upper() for name in cls.model_fields}
        data: dict[str, str] = {}

        path = Path(env_file) if env_file is not None else DEFAULT_ENV_FILE
        data.update({k: v for k, v in _load_env_file(path).items() if k in allowed})

        source = os.environ if environ is None else environ
        data.update({k: v for k, v in source.items() if k in allowed})

        try:
            return cls(**data)
        except ValidationError as exc:
            detail = "\n".join(
                f"  - {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
            )
            raise RuntimeError(
                f"配置校验失败（来源：{path} + 环境变量）：\n{detail}\n"
                f"请对照 {BACKEND_DIR / '.env.example'} 补全 backend/.env"
            ) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。测试时用 cache_clear() 重置。"""
    return Settings.from_env()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
