"""P8-01：Service 层分支测试（用假仓储/假模型，不连库）。"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import AuthRequired, DependencyUnavailable, Forbidden, NotFound
from app.core.security import create_refresh_token, hash_password
from app.services.auth_service import AuthService
from app.services.conversation_service import ConversationService
from app.services.kb_service import KbService

SETTINGS = SimpleNamespace(
    jwt_secret="0123456789abcdef0123456789abcdef",
    jwt_alg="HS256",
    jwt_expire_minutes=60,
    jwt_refresh_expire_days=7,
    upload_max_mb=1,
)


# ---------- AuthService ----------
class FakeUsers:
    def __init__(self, user: dict | None):
        self.user = user
        self.fail_count = 0
        self.reset_called = False
        self.profile = {"student_no": "20230001", "name": "张三"}

    async def get_by_username(self, username: str):
        if self.user and self.user["username"] == username:
            return self.user
        return None

    async def get_by_id(self, user_id: int):
        return self.user if self.user and self.user["id"] == user_id else None

    async def register_failure(self, user_id: int, *, threshold: int = 5, lock_minutes: int = 10):
        self.fail_count += 1
        row = {"fail_count": self.fail_count, "locked_until": None}
        if self.fail_count >= threshold:
            row["locked_until"] = datetime.now() + timedelta(minutes=lock_minutes)
        return row

    async def reset_failure(self, user_id: int):
        self.reset_called = True

    async def get_profile(self, user_id: int):
        return self.profile


def make_user(**overrides):
    user = {
        "id": 1,
        "username": "u1",
        "role": "student",
        "password_hash": hash_password("pw123456"),
        "status": "active",
        "fail_count": 0,
        "locked_until": None,
    }
    user.update(overrides)
    return user


def test_auth_login_success_and_current_user():
    users = FakeUsers(make_user())
    svc = AuthService(SETTINGS, users)
    tokens = asyncio.run(svc.login("u1", "pw123456"))
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert users.reset_called is True

    me = asyncio.run(svc.current_user(1, "student"))
    assert me["student_no"] == "20230001"
    admin = asyncio.run(svc.current_user(1, "admin"))
    assert admin["student_no"] is None


def test_auth_login_failures():
    svc = AuthService(SETTINGS, FakeUsers(None))
    with pytest.raises(AuthRequired):
        asyncio.run(svc.login("missing", "pw"))

    svc = AuthService(SETTINGS, FakeUsers(make_user(status="disabled")))
    with pytest.raises(Forbidden):
        asyncio.run(svc.login("u1", "pw123456"))

    locked = make_user(locked_until=datetime.now() + timedelta(minutes=5))
    svc = AuthService(SETTINGS, FakeUsers(locked))
    with pytest.raises(Forbidden):
        asyncio.run(svc.login("u1", "pw123456"))


def test_auth_wrong_password_locks_after_threshold():
    users = FakeUsers(make_user())
    svc = AuthService(SETTINGS, users)
    with pytest.raises(AuthRequired):
        asyncio.run(svc.login("u1", "wrong"))
    for _ in range(4):  # 第 5 次触发锁定
        with pytest.raises((AuthRequired, Forbidden)):
            asyncio.run(svc.login("u1", "wrong"))
    assert users.fail_count >= 5


def test_auth_refresh_and_missing_user():
    users = FakeUsers(make_user())
    svc = AuthService(SETTINGS, users)
    token = create_refresh_token(SETTINGS, user_id=1, role="student")
    assert asyncio.run(svc.refresh(token))["access_token"]
    with pytest.raises(AuthRequired):
        asyncio.run(svc.refresh("not-a-token"))
    with pytest.raises(AuthRequired):
        asyncio.run(svc.current_user(99, "student"))


# ---------- ConversationService ----------
class FakeConvRepo:
    def __init__(self):
        self.records = {1: {"id": 1, "user_id": 1, "title": "新会话"}}
        self.renamed = False
        self.deleted = False

    async def create(self, *, user_id, role_mode, title):
        self.records[2] = {"id": 2, "user_id": user_id, "title": title}
        return 2

    async def get(self, *, user_id, conversation_id):
        rec = self.records.get(conversation_id)
        return rec if rec and rec["user_id"] == user_id else None

    async def list_by_user(self, *, user_id, page, size):
        return [self.records[1]], 1

    async def rename(self, *, user_id, conversation_id, title):
        self.renamed = True
        return conversation_id in self.records

    async def soft_delete(self, *, user_id, conversation_id):
        self.deleted = True
        return conversation_id in self.records

    async def list_traces(self, *, conversation_id, limit=50):
        return [{"id": 1}]

    async def list_messages(self, *, conversation_id, page, size):
        return [{"id": 11, "role": "assistant", "content": "答"}], 1

    async def list_citations_bulk(self, message_ids):
        return {11: [{"kb_file_id": 1, "snippet": "证据"}]}


def test_conversation_service_crud_and_messages():
    svc = ConversationService(FakeConvRepo())
    created = asyncio.run(svc.create(user_id=1, role_mode="student", title=None))
    assert created["id"] == 2
    listed = asyncio.run(svc.list(user_id=1, page=1, size=20))
    assert listed["total"] == 1
    assert asyncio.run(svc.get(user_id=1, conversation_id=1))["id"] == 1
    assert asyncio.run(svc.rename(user_id=1, conversation_id=1, title="x"))["id"] == 1
    assert asyncio.run(svc.traces(user_id=1, conversation_id=1)) == [{"id": 1}]
    messages = asyncio.run(svc.messages(user_id=1, conversation_id=1, page=1, size=20))
    assert messages["items"][0]["citations"][0]["snippet"] == "证据"
    asyncio.run(svc.delete(user_id=1, conversation_id=1))

    with pytest.raises(NotFound):
        asyncio.run(svc.get(user_id=2, conversation_id=1))
    with pytest.raises(NotFound):
        asyncio.run(svc.rename(user_id=1, conversation_id=99, title="x"))
    with pytest.raises(NotFound):
        asyncio.run(svc.delete(user_id=1, conversation_id=99))


# ---------- KbService ----------
class FakeKbRepo:
    def __init__(self):
        self.files = {
            1: {
                "id": 1,
                "filename": "a.pdf",
                "file_hash": "h1",
                "file_type": "pdf",
                "deleted_at": None,
            }
        }
        self.status_updates = []
        self.tasks = []
        self.chunks = {}
        self.revived = False

    async def find_by_hash(self, file_hash, *, include_deleted=False):
        for item in self.files.values():
            if item.get("file_hash") == file_hash and (include_deleted or not item.get("deleted_at")):
                return item
        return None

    async def revive_file(self, file_id, **kwargs):
        self.revived = True

    async def create_file(self, **kwargs):
        self.files[2] = {"id": 2, "deleted_at": None, **kwargs}
        return 2

    async def add_task(self, file_id, *, stage, status="pending"):
        self.tasks.append((file_id, stage, status))
        return len(self.tasks)

    async def get_file(self, file_id):
        return self.files.get(file_id)

    async def update_status(self, file_id, *, status, channel=None, chunk_count=None):
        self.status_updates.append((file_id, status))

    async def replace_chunks(self, file_id, rows):
        self.chunks[file_id] = rows

    async def list_files(self, *, page, size, status):
        return [self.files[1]], 1

    async def list_chunks(self, *, file_id, page, size):
        return self.chunks.get(file_id, []), len(self.chunks.get(file_id, []))

    async def soft_delete(self, file_id):
        return True

    async def start_task(self, task_id):
        self.tasks.append(("start", task_id))

    async def finish_task(self, task_id, *, status, error=None):
        self.tasks.append(("finish", status, error))


class FakeStore:
    def __init__(self):
        self.deleted = []

    def delete_by_file(self, file_id):
        self.deleted.append(file_id)


class FakeIndexer:
    async def index_file(self, **kwargs):
        return SimpleNamespace(channel="pdf-text", chunk_count=3)


def make_kb(tmp_path: Path):
    repo = FakeKbRepo()
    store = FakeStore()
    svc = KbService(
        settings=SETTINGS,
        repo=repo,
        indexer=FakeIndexer(),
        store=store,
        upload_dir=tmp_path,
    )
    svc._spawn = lambda coro: coro.close()  # 避免后台任务在测试里继续跑
    return svc, repo, store


def test_kb_upload_validation_and_success(tmp_path):
    svc, repo, _ = make_kb(tmp_path)
    with pytest.raises(Exception):
        asyncio.run(svc.upload(filename="a.exe", content=b"x", uploaded_by=1))
    with pytest.raises(Exception):
        asyncio.run(svc.upload(filename="a.pdf", content=b"", uploaded_by=1))
    with pytest.raises(Exception):
        asyncio.run(svc.upload(filename="a.pdf", content=b"x" * (2 * 1024 * 1024), uploaded_by=1))

    record = asyncio.run(svc.upload(filename="a.pdf", content=b"%PDF-1.4", uploaded_by=1))
    assert record["id"] == 2
    assert (tmp_path / f"{record['file_hash']}.pdf").is_file()


def test_kb_upload_write_failure(tmp_path, monkeypatch):
    svc, _, _ = make_kb(tmp_path)

    def boom(self, data):
        raise OSError("No space left on device")

    monkeypatch.setattr(Path, "write_bytes", boom)
    with pytest.raises(DependencyUnavailable) as exc:
        asyncio.run(svc.upload(filename="a.pdf", content=b"%PDF", uploaded_by=1))
    assert "存储空间不足" in str(exc.value)


def test_kb_upload_revives_deleted_file(tmp_path):
    svc, repo, _ = make_kb(tmp_path)
    content = b"%PDF-revive"
    digest = hashlib.sha256(content).hexdigest()
    repo.files[9] = {
        "id": 9,
        "filename": "old.pdf",
        "file_hash": digest,
        "file_type": "pdf",
        "deleted_at": datetime.now(),
    }
    record = asyncio.run(svc.upload(filename="new.pdf", content=content, uploaded_by=1))
    assert record["id"] == 9
    assert repo.revived is True

    svc, repo, store = make_kb(tmp_path)
    assert asyncio.run(svc.get_file(1))["id"] == 1
    assert asyncio.run(svc.list_files(page=1, size=20, status=None))["total"] == 1
    assert asyncio.run(svc.list_chunks(file_id=1, page=1, size=20))["total"] == 0

    asyncio.run(svc.delete(1))
    assert store.deleted == [1]

    (tmp_path / "h1.pdf").write_bytes(b"%PDF")
    assert asyncio.run(svc.reindex(1))["id"] == 1

    with pytest.raises(NotFound):
        asyncio.run(svc.get_file(99))
