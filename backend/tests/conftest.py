"""测试公共夹具。

约定：
- 不连真实 MySQL：Database.connect 被替换成 no-op，ping 恒为 False。
- 需要真库的用例用 @pytest.mark.integration 并检查 TEST_MYSQL 环境变量。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.pool import Database
from app.main import create_app

BASE_ENV = {
    "APP_ENV": "test",
    "MYSQL_USER": "root",
    "MYSQL_PASSWORD": "db-pass",
    "JWT_SECRET": "0123456789abcdef0123456789abcdef",
    "LLM_BASE_URL": "http://127.0.0.1:8001/v1",
    "EMBED_BASE_URL": "http://127.0.0.1:8002",
    "RERANK_BASE_URL": "http://127.0.0.1:8002",
    "OCR_BASE_URL": "http://127.0.0.1:8002",
}


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.from_env(env_file=None, environ=BASE_ENV)


@pytest.fixture()
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    async def _noop_connect(self: Database) -> None:
        self.last_error = "测试环境未连接数据库"

    monkeypatch.setattr(Database, "connect", _noop_connect)
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
