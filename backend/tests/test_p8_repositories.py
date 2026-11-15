"""P8-01/02：仓储层集成测试（需要独立测试库）。

运行：
    MYSQL_DB=campus_assistant_test TEST_MYSQL=1 pytest tests/test_p8_repositories.py -q
"""

from __future__ import annotations

import os

import pytest

from app.core.config import Settings
from app.db.pool import Database
from app.repositories.conversations import ConversationRepository
from app.repositories.kb import KbRepository
from app.repositories.search_cache import SearchCacheRepository
from app.repositories.users import UserRepository

pytestmark = pytest.mark.skipif(os.getenv("TEST_MYSQL") != "1", reason="需要真实 MySQL")


async def _truncate_all(db: Database) -> None:
    async with db.cursor() as cur:
        await cur.execute("SET FOREIGN_KEY_CHECKS=0")
        await cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()"
        )
        tables = [row.get("table_name") or row.get("TABLE_NAME") for row in await cur.fetchall()]
        for table in tables:
            if table == "schema_version":
                continue
            await cur.execute(f"TRUNCATE TABLE `{table}`")
        await cur.execute("SET FOREIGN_KEY_CHECKS=1")


@pytest.fixture()
async def db():
    settings = Settings.from_env()
    assert settings.mysql_db.endswith("_test"), "仓储集成测试只能跑 *_test 库"
    database = Database(settings)
    await database.connect()
    await _truncate_all(database)
    yield database
    await database.close()


@pytest.fixture()
async def user_id(db):
    repo = UserRepository(db)
    return await repo.create(username="u-test", password_hash="x", role="student")


async def test_user_repository(db, user_id):
    repo = UserRepository(db)
    user = await repo.get_by_username("u-test")
    assert user["id"] == user_id
    assert (await repo.get_by_id(user_id))["username"] == "u-test"
    assert await repo.get_by_username("missing") is None
    assert await repo.count() == 1

    row = await repo.register_failure(user_id, threshold=2, lock_minutes=5)
    assert row["fail_count"] == 1
    row = await repo.register_failure(user_id, threshold=2, lock_minutes=5)
    assert row["fail_count"] == 2 and row["locked_until"] is not None
    assert UserRepository.is_locked(row)[0] is True

    await repo.reset_failure(user_id)
    fresh = await repo.get_by_username("u-test")
    assert fresh["fail_count"] == 0 and fresh["locked_until"] is None

    assert await repo.get_profile(user_id) is None
    await repo.save_edu_binding(
        user_id=user_id, student_no="20230001", edu_username="20230001", cred_cipher=b"cipher"
    )
    binding = await repo.get_edu_binding(user_id)
    assert binding["edu_username"] == "20230001" and binding["edu_cred_cipher"] == b"cipher"
    await repo.clear_edu_binding(user_id)
    assert (await repo.get_edu_binding(user_id))["edu_username"] is None


async def test_conversation_repository(db, user_id):
    repo = ConversationRepository(db)
    conv_id = await repo.create(user_id=user_id, role_mode="student", title="测试会话")
    assert (await repo.get(user_id=user_id, conversation_id=conv_id))["title"] == "测试会话"
    items, total = await repo.list_by_user(user_id=user_id, page=1, size=20)
    assert total == 1 and items[0]["id"] == conv_id

    assert await repo.rename(user_id=user_id, conversation_id=conv_id, title="改名") is True
    assert await repo.rename(user_id=user_id, conversation_id=999, title="x") is False

    msg_id = await repo.add_message(
        conversation_id=conv_id, role="assistant", content="回答", latency_ms=12, trace_id="t1"
    )
    await repo.add_citations(
        message_id=msg_id,
        items=[{"kb_file_id": None, "chunk_id": "c1", "page_no": 1, "snippet": "证据", "score": 0.9}],
    )
    msgs, total = await repo.list_messages(conversation_id=conv_id, page=1, size=20)
    assert total == 1 and msgs[0]["content"] == "回答"
    assert (await repo.list_citations(message_id=msg_id))[0]["snippet"] == "证据"
    bulk = await repo.list_citations_bulk([msg_id])
    assert bulk[msg_id][0]["snippet"] == "证据"

    await repo.add_trace(
        conversation_id=conv_id,
        message_id=msg_id,
        trace_id="t1",
        intent="kb",
        keywords="勤工助学",
        degraded=None,
        evidence_count=1,
        prompt_version="p3-v4",
        nodes=[{"node": "retrieve", "kept": 1}],
        latency_ms=12,
    )
    traces = await repo.list_traces(conversation_id=conv_id)
    assert traces[0]["nodes"][0]["node"] == "retrieve"

    await repo.touch(conv_id)
    assert await repo.soft_delete(user_id=user_id, conversation_id=conv_id) is True
    assert (await repo.list_messages(conversation_id=conv_id, page=1, size=20))[1] == 0
    assert await repo.soft_delete(user_id=user_id, conversation_id=conv_id) is False


async def test_kb_repository(db, user_id):
    repo = KbRepository(db)
    file_id = await repo.create_file(
        filename="测试.pdf",
        file_hash="h" * 64,
        file_type="pdf",
        size_bytes=123,
        source_dept="学工处",
        source_url=None,
        effective_from=None,
        effective_to=None,
        uploaded_by=user_id,
    )
    assert (await repo.find_by_hash("h" * 64))["id"] == file_id
    assert (await repo.get_files_by_ids([file_id]))[file_id]["filename"] == "测试.pdf"
    assert (await repo.get_files_by_ids([])) == {}

    await repo.update_status(file_id, status="success", channel="pdf-text", chunk_count=2)
    assert (await repo.get_file(file_id))["chunk_count"] == 2
    assert "测试.pdf" in await repo.list_titles(limit=10)

    items, total = await repo.list_files(page=1, size=20, status="success")
    assert total == 1 and items[0]["id"] == file_id
    assert (await repo.list_files(page=1, size=20, status="failed"))[1] == 0

    await repo.replace_chunks(
        file_id,
        [
            {
                "ordinal": 1,
                "content": "切片一",
                "token_count": 10,
                "vector_id": "v1",
                "meta_json": "{}",
            },
            {
                "ordinal": 2,
                "content": "切片二",
                "token_count": 10,
                "vector_id": "v2",
                "meta_json": "{}",
            },
        ],
    )
    chunks, total = await repo.list_chunks(file_id=file_id, page=1, size=20)
    assert total == 2 and chunks[0]["ordinal"] == 1

    task_id = await repo.add_task(file_id, stage="pipeline")
    await repo.start_task(task_id)
    await repo.finish_task(task_id, status="success")
    async with db.cursor() as cur:
        await cur.execute("SELECT status FROM parse_task WHERE id=%s", (task_id,))
        assert (await cur.fetchone())["status"] == "success"

    assert await repo.soft_delete(file_id) is True
    assert await repo.soft_delete(file_id) is False


async def test_search_cache_repository(db):
    repo = SearchCacheRepository(db)
    await repo.put("hash-1", [{"title": "结果"}], hours=1)
    assert (await repo.get("hash-1"))[0]["title"] == "结果"
    assert await repo.get("missing") is None

    key = "test:daily:unique"
    assert await repo.consume_daily(key, 2) is True
    assert await repo.consume_daily(key, 2) is True
    assert await repo.consume_daily(key, 2) is False
    assert await repo.today_usage(key) == 3
