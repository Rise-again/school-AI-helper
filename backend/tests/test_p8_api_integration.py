"""P8-02：接口集成测试（真实测试库 + 假服务依赖）。

覆盖 21 个路径的主要操作，每类接口至少 1 正例 + 2 反例（401/403/422/404/405）。
运行：MYSQL_DB=campus_assistant_test TEST_MYSQL=1 pytest tests/test_p8_api_integration.py -q
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import aiomysql
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_chat_service, get_edu_service, get_kb_service, get_retriever
from app.core.config import Settings
from app.core.errors import NotFound
from app.core.security import hash_password
from app.main import create_app

pytestmark = pytest.mark.skipif(os.getenv("TEST_MYSQL") != "1", reason="需要真实测试库")

ADMIN = ("admin", "Admin@12345")
STUDENT = ("20230001", "Student@123")


async def _seed() -> None:
    settings = Settings.from_env()
    assert settings.mysql_db.endswith("_test")
    conn = await aiomysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        db=settings.mysql_db,
        autocommit=True,
        charset="utf8mb4",
        cursorclass=aiomysql.DictCursor,
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute("SET FOREIGN_KEY_CHECKS=0")
            await cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()"
            )
            for row in await cur.fetchall():
                name = row.get("table_name") or row.get("TABLE_NAME")
                if name != "schema_version":
                    await cur.execute(f"TRUNCATE TABLE `{name}`")
            await cur.execute("SET FOREIGN_KEY_CHECKS=1")
            for username, password, role in [
                ("admin", "Admin@12345", "admin"),
                ("20230001", "Student@123", "student"),
                ("20230002", "Student@123", "student"),
            ]:
                await cur.execute(
                    "INSERT INTO user_account (username, role, password_hash) VALUES (%s,%s,%s)",
                    (username, role, hash_password(password)),
                )
                user_id = cur.lastrowid
                if role == "student":
                    await cur.execute(
                        "INSERT INTO student_profile (user_id, student_no, name, college, major, grade) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (user_id, username, "测试学生", "计算机学院", "计算机科学与技术", "2023"),
                    )
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client():
    asyncio.run(_seed())
    settings = Settings.from_env()
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_auth_contract(client):
    assert client.post("/api/v1/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": ADMIN[0], "password": "bad"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "missing", "password": "x"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "1", "password": ""}).status_code == 422

    token = _login(client, *STUDENT)
    refresh = client.post("/api/v1/auth/login", json={"username": STUDENT[0], "password": STUDENT[1]}).json()["data"]["refresh_token"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": "short"}).status_code == 422
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid-token"}).status_code == 401
    assert client.post("/api/v1/auth/logout").status_code == 200

    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer bad"}).status_code == 401
    me = client.get("/api/v1/me", headers=_headers(token))
    assert me.status_code == 200 and me.json()["data"]["role"] == "student"


def test_conversation_contract(client):
    student = _login(client, *STUDENT)
    admin = _login(client, *ADMIN)
    assert client.get("/api/v1/conversations").status_code == 401
    assert client.get("/api/v1/conversations?size=0", headers=_headers(student)).status_code == 422

    created = client.post("/api/v1/conversations", json={"title": "集成测试"}, headers=_headers(student))
    assert created.status_code == 200
    conv_id = created.json()["data"]["id"]
    assert client.get("/api/v1/conversations", headers=_headers(student)).status_code == 200
    assert client.get(f"/api/v1/conversations/{conv_id}", headers=_headers(student)).status_code == 200
    assert client.get(f"/api/v1/conversations/{conv_id}", headers=_headers(admin)).status_code == 404

    assert client.patch(f"/api/v1/conversations/{conv_id}", json={"title": ""}, headers=_headers(student)).status_code == 422
    assert client.patch(f"/api/v1/conversations/{conv_id}", json={"title": "改名"}, headers=_headers(student)).status_code == 200
    assert client.get(f"/api/v1/conversations/{conv_id}/messages", headers=_headers(student)).status_code == 200
    assert client.get(f"/api/v1/conversations/{conv_id}/trace", headers=_headers(student)).status_code == 200
    assert client.get("/api/v1/conversations/999999", headers=_headers(student)).status_code == 404

    assert client.delete(f"/api/v1/conversations/{conv_id}", headers=_headers(student)).status_code == 200
    assert client.delete(f"/api/v1/conversations/{conv_id}", headers=_headers(student)).status_code == 404


class FakeKb:
    def __init__(self):
        now = datetime.now()
        self.row = {
            "id": 1,
            "filename": "a.pdf",
            "file_type": "pdf",
            "size_bytes": 10,
            "parse_status": "success",
            "chunk_count": 1,
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }

    async def list_files(self, *, page, size, status):
        return {"items": [self.row], "total": 1, "page": page, "size": size}

    async def get_file(self, file_id):
        if file_id != 1:
            raise NotFound("文件不存在")
        return self.row

    async def list_chunks(self, *, file_id, page, size):
        return {
            "items": [
                {
                    "id": 1,
                    "ordinal": 1,
                    "content": "切片",
                    "token_count": 2,
                    "vector_id": "v1",
                    "meta_json": "{}",
                    "created_at": datetime.now(),
                }
            ],
            "total": 1,
            "page": page,
            "size": size,
        }

    async def reindex(self, file_id):
        return self.row

    async def delete(self, file_id):
        if file_id != 1:
            raise NotFound("文件不存在")

    async def upload(self, **kwargs):
        return self.row


def test_kb_contract(client):
    admin = _login(client, *ADMIN)
    student = _login(client, *STUDENT)
    client.app.dependency_overrides[get_kb_service] = lambda: FakeKb()
    try:
        assert client.get("/api/v1/kb/files").status_code == 401
        assert client.get("/api/v1/kb/files", headers=_headers(student)).status_code == 403
        assert client.get("/api/v1/kb/files?status=bad", headers=_headers(admin)).status_code == 422
        assert client.get("/api/v1/kb/files", headers=_headers(admin)).status_code == 200
        assert client.get("/api/v1/kb/files/1", headers=_headers(admin)).status_code == 200
        assert client.get("/api/v1/kb/files/999", headers=_headers(admin)).status_code == 404
        assert client.get("/api/v1/kb/files/1/chunks", headers=_headers(admin)).status_code == 200
        assert client.post("/api/v1/kb/files/1/reindex", headers=_headers(admin)).status_code == 200
        assert client.post("/api/v1/kb/files", headers=_headers(admin)).status_code == 422
        upload = client.post(
            "/api/v1/kb/files",
            headers=_headers(admin),
            files={"file": ("a.pdf", b"%PDF", "application/pdf")},
            data={"effective_from": "not-a-date"},
        )
        assert upload.status_code == 422
        assert client.delete("/api/v1/kb/files/1", headers=_headers(admin)).status_code == 200
    finally:
        client.app.dependency_overrides.clear()


class FakeEdu:
    async def status(self, user_id):
        return {"bound": True, "student_no": "20230001", "updated_at": None}

    async def bind(self, **kwargs):
        return await self.status(kwargs["user_id"])

    async def unbind(self, user_id):
        return None

    async def schedule(self, user_id):
        return []

    async def grades(self, user_id, term=None):
        return {"terms": [], "items": []}

    async def credits(self, user_id):
        return {"required": 0, "earned": 0, "gpa": 0, "categories": []}


def test_edu_contract(client):
    student = _login(client, *STUDENT)
    admin = _login(client, *ADMIN)
    client.app.dependency_overrides[get_edu_service] = lambda: FakeEdu()
    try:
        assert client.get("/api/v1/edu/status").status_code == 401
        assert client.get("/api/v1/edu/status", headers=_headers(admin)).status_code == 403
        assert client.get("/api/v1/edu/status", headers=_headers(student)).status_code == 200
        assert client.post("/api/v1/edu/bind", json={"student_no": "1", "password": "x"}, headers=_headers(admin)).status_code == 403
        assert client.post("/api/v1/edu/bind", json={"student_no": "", "password": ""}, headers=_headers(student)).status_code == 422
        assert client.post("/api/v1/edu/bind", json={"student_no": "20230001", "password": "p"}, headers=_headers(student)).status_code == 200
        assert client.delete("/api/v1/edu/bind", headers=_headers(student)).status_code == 200
        assert client.get("/api/v1/edu/schedule", headers=_headers(student)).status_code == 200
        assert client.get("/api/v1/edu/grades?term=" + "x" * 20, headers=_headers(student)).status_code == 422
        assert client.get("/api/v1/edu/credits", headers=_headers(student)).status_code == 200
    finally:
        client.app.dependency_overrides.clear()


class FakeRetriever:
    async def search(self, q, *, top_n=None, include_expired=False):
        return []


class FakeChat:
    async def classify(self, q, history=None):
        return "kb"

    async def ensure_owned(self, **kwargs):
        return None

    async def stream_reply(self, **kwargs):
        yield "meta", {"intent": "kb", "evidence_count": 1}
        yield "delta", {"text": "好"}
        yield "done", {"latency_ms": 1, "chars": 1}

    async def stream_guest(self, **kwargs):
        async for event in self.stream_reply(**kwargs):
            yield event

    def ensure_allowed(self, **kwargs):
        return None


def test_rag_and_chat_contract(client):
    admin = _login(client, *ADMIN)
    student = _login(client, *STUDENT)
    client.app.dependency_overrides[get_retriever] = lambda: FakeRetriever()
    client.app.dependency_overrides[get_chat_service] = lambda: FakeChat()
    try:
        assert client.get("/api/v1/rag/search?q=勤工助学").status_code == 401
        assert client.get("/api/v1/rag/search?q=勤工助学", headers=_headers(student)).status_code == 403
        assert client.get("/api/v1/rag/search", headers=_headers(admin)).status_code == 422
        assert client.get("/api/v1/rag/search?q=勤工助学", headers=_headers(admin)).status_code == 200
        assert client.get("/api/v1/rag/intent?q=勤工助学", headers=_headers(admin)).status_code == 200

        assert client.post("/api/v1/chat/anonymous", json={"content": ""}).status_code == 422
        assert client.get("/api/v1/chat/anonymous").status_code == 405
        sse = client.post("/api/v1/chat/anonymous", json={"content": "你好"})
        assert sse.status_code == 200 and "event: delta" in sse.text

        assert client.post("/api/v1/conversations/1/messages", json={"content": "hi"}).status_code == 401
        assert client.post("/api/v1/conversations/1/messages", json={"content": ""}, headers=_headers(student)).status_code == 422
        sse2 = client.post(
            "/api/v1/conversations/1/messages", json={"content": "hi"}, headers=_headers(student)
        )
        assert sse2.status_code == 200 and "event: done" in sse2.text
    finally:
        client.app.dependency_overrides.clear()
