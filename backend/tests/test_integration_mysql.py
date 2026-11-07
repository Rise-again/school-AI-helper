"""需要真实 MySQL 的集成测试。

运行前提：
    1. 本机 MySQL 已启动，backend/.env 配好
    2. python scripts/migrate.py
    3. python scripts/seed_demo.py
    4. 设 TEST_MYSQL=1 再跑：TEST_MYSQL=1 pytest tests/test_integration_mysql.py -v

未设置 TEST_MYSQL 时整组跳过，不会污染日常单测。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("TEST_MYSQL") != "1",
    reason="需要真实 MySQL，设置 TEST_MYSQL=1 后运行",
)

ADMIN = ("admin", "Admin@12345")
STUDENT = ("20230001", "Student@123")


@pytest.fixture(scope="module")
def client():
    settings = Settings.from_env()  # 读 backend/.env
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def test_wrong_password_rejected(client):
    resp = client.post("/api/v1/auth/login", json={"username": STUDENT[0], "password": "wrong-pass"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 2001


def test_login_and_me(client):
    token = _login(client, *STUDENT)
    resp = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["role"] == "student"
    assert body["student_no"] == "20230001"


def test_refresh_issues_new_pair(client):
    token = _login(client, *STUDENT)
    tokens = client.post("/api/v1/auth/login", json={"username": STUDENT[0], "password": STUDENT[1]}).json()["data"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["data"]["access_token"] != token


def test_conversation_lifecycle(client):
    token = _login(client, *STUDENT)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post("/api/v1/conversations", json={"title": "测试会话"}, headers=headers)
    assert created.status_code == 200, created.text
    conv_id = created.json()["data"]["id"]

    listed = client.get("/api/v1/conversations", headers=headers).json()["data"]
    assert any(item["id"] == conv_id for item in listed["items"])

    renamed = client.patch(
        f"/api/v1/conversations/{conv_id}", json={"title": "改名后"}, headers=headers
    )
    assert renamed.json()["data"]["title"] == "改名后"

    detail = client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert detail.status_code == 200

    deleted = client.delete(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert deleted.status_code == 200

    gone = client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert gone.status_code == 404
    assert gone.json()["code"] == 3001


def test_cannot_read_other_users_conversation(client):
    admin_token = _login(client, *ADMIN)
    student_token = _login(client, *STUDENT)

    created = client.post(
        "/api/v1/conversations",
        json={"title": "管理员会话"},
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()["data"]

    resp = client.get(
        f"/api/v1/conversations/{created['id']}",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 404  # 不暴露"存在但不属于你"
