"""教务接入的单元测试：映射、加密、缓存与会话重登。

不连真实教务系统，用 FakeEduClient 模拟 SDK 返回。
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import Any

import pytest

from app.core.config import Settings
from app.core.crypto import decrypt_secret, encrypt_secret, _cred_key
from app.integrations.edu import (
    EduAuthError,
    EduSession,
    EduSessionExpired,
    EduUnavailable,
)
from app.services.edu_service import (
    EduNotBound,
    EduService,
    aggregate_credits,
    current_term,
    map_schedule,
    map_score_items,
    parse_term_label,
    term_label,
)
from tests.conftest import BASE_ENV


def _settings() -> Settings:
    return Settings.from_env(env_file=None, environ=BASE_ENV)


SCHEDULE_RAW = {
    "class_name": "25计算机科学与技术1班",
    "username": "张三",
    "course_list": [
        {
            "course": "大学英语-3",
            "place": "4207",
            "campus": "三亚校区",
            "teacher": "周荣",
            "weeks_text": "1-17周",
            "week_day": "1",
            "week_day_text": "星期一",
            "section": "1-2",
        },
        {
            "course": "数据结构",
            "place": "3401",
            "teacher": "",
            "weeks_text": "3-16周(单)",
            "week_day": "",
            "week_day_text": "星期三",
            "section": "3",
        },
    ],
}

SCORES_RAW = {
    "数据结构": {
        "course_name": "数据结构",
        "course_nature": "学科基础课",
        "exam_result": "72",
        "exam_score": "72",
        "credit": "4",
        "grade_point": "2.20",
    },
    "红木鉴赏": {
        "course_name": "红木鉴赏与收藏#",
        "course_nature": "通识类课(选修)",
        "exam_result": "不合格",
        "exam_score": "0",
        "credit": "2.0",
        "grade_point": None,
    },
}


# ---------------- 学期换算 ----------------


def test_current_term_by_month():
    assert current_term(date(2026, 11, 14)) == (2026, 1)
    assert current_term(date(2026, 2, 1)) == (2025, 2)
    assert current_term(date(2026, 8, 1)) == (2026, 1)


def test_term_label_roundtrip():
    assert term_label(2025, 2) == "2025-2026-2"
    assert parse_term_label("2025-2026-2") == (2025, 2)
    assert parse_term_label("2025-2026-3") is None
    assert parse_term_label("2025-2027-2") is None
    assert parse_term_label("2025-2026") is None


# ---------------- 映射 ----------------


def test_map_schedule_fields():
    items = map_schedule(SCHEDULE_RAW)
    assert items[0] == {
        "weekday": 1,
        "sections": [1, 2],
        "course": "大学英语-3",
        "teacher": "周荣",
        "location": "4207",
        "weeks": "1-17周",
    }
    # 星期缺失时用中文回退；节次单个数字
    assert items[1]["weekday"] == 3
    assert items[1]["sections"] == [3]
    assert items[1]["teacher"] is None


def test_map_scores_and_credits():
    items = map_score_items(SCORES_RAW, "2025-2026-2")
    assert items[0]["course"] == "数据结构"
    assert items[0]["credit"] == 4.0
    assert items[0]["gpa"] == 2.2
    assert items[1]["score"] == "不合格"

    summary = aggregate_credits(items)
    # 不合格不计入学分；绩点按有绩点的课程加权
    assert summary["earned"] == 4.0
    assert summary["gpa"] == 2.2
    assert summary["required"] == 0.0
    assert {"name": "学科基础课", "required": 0.0, "earned": 4.0} in summary["categories"]


def test_text_scores_pass_and_fail():
    items = map_score_items(
        {
            "a": {"course_name": "A", "exam_result": "合格", "credit": "1", "grade_point": None},
            "b": {"course_name": "B", "exam_result": "缺考", "credit": "2", "grade_point": None},
        },
        "2025-2026-1",
    )
    summary = aggregate_credits(items)
    assert summary["earned"] == 1.0


# ---------------- 加密 ----------------


def test_cred_cipher_roundtrip_and_aad():
    settings = _settings()
    blob = encrypt_secret(settings, 7, "s3cret!")
    assert blob != b"s3cret!"
    assert decrypt_secret(settings, 7, blob) == "s3cret!"
    with pytest.raises(Exception):
        decrypt_secret(settings, 8, blob)  # AAD 绑定 user_id
    assert len(_cred_key(settings)) == 32


# ---------------- 服务层（Fake 客户端） ----------------


class FakeRepo:
    def __init__(self) -> None:
        self.rows: dict[int, dict[str, Any]] = {}

    async def get_edu_binding(self, user_id: int):
        return self.rows.get(user_id)

    async def save_edu_binding(self, *, user_id, student_no, edu_username, cred_cipher):
        self.rows[user_id] = {
            "student_no": student_no,
            "edu_username": edu_username,
            "edu_cred_cipher": cred_cipher,
            "edu_bound_at": None,
        }

    async def clear_edu_binding(self, user_id: int):
        self.rows.pop(user_id, None)


class FakeClient:
    def __init__(self) -> None:
        self.logins = 0
        self.schedule_calls = 0
        self.score_calls = 0
        self.expire_once = False
        self.fail_login = False

    def login(self, account: str, password: str) -> EduSession:
        if self.fail_login:
            raise EduAuthError("bad")
        self.logins += 1
        return EduSession(account=account, raw=object())

    def info(self, session: EduSession):
        return {"student_number": session.account}

    def schedule(self, session: EduSession, year: int, term: int):
        self.schedule_calls += 1
        return SCHEDULE_RAW

    def scores(self, session: EduSession, year: int, term: int):
        self.score_calls += 1
        if self.expire_once:
            self.expire_once = False
            raise EduSessionExpired("expired")
        return SCORES_RAW if term == 2 else {}


def _service() -> tuple[EduService, FakeRepo, FakeClient]:
    repo, client = FakeRepo(), FakeClient()
    return EduService(settings=_settings(), users=repo, client=client), repo, client


def test_bind_status_unbind():
    svc, repo, client = _service()

    async def run() -> None:
        before = await svc.status(1)
        assert before["bound"] is False
        status = await svc.bind(user_id=1, student_no="20250001", password="pw")
        assert status["bound"] is True
        assert status["student_no"] == "20250001"
        # 密文入库，明文不出现
        assert repo.rows[1]["edu_cred_cipher"] != b"pw"
        await svc.unbind(1)
        assert (await svc.status(1))["bound"] is False

    asyncio.run(run())


def test_bind_wrong_password():
    svc, _, client = _service()
    client.fail_login = True

    async def run() -> None:
        with pytest.raises(Exception) as exc:
            await svc.bind(user_id=1, student_no="1", password="bad")
        assert "密码" in str(exc.value)

    asyncio.run(run())


def test_schedule_cached_and_session_reused():
    svc, _, client = _service()

    async def run() -> None:
        await svc.bind(user_id=1, student_no="s", password="pw")
        first = await svc.schedule(1)
        second = await svc.schedule(1)
        assert first == second and len(first) == 2
        assert client.schedule_calls == 1  # TTL 内不重复请求
        assert client.logins == 1  # 复用会话

    asyncio.run(run())


def test_session_expired_relogin_once():
    svc, _, client = _service()

    async def run() -> None:
        await svc.bind(user_id=1, student_no="s", password="pw")
        client.expire_once = True
        items = await svc.all_scores(1)
        assert items  # 重登后拿到了数据
        assert client.logins == 2  # 绑定 1 次 + 失效重登 1 次

    asyncio.run(run())


def test_cooldown_serves_stale_cache():
    svc, _, client = _service()

    async def run() -> None:
        await svc.bind(user_id=1, student_no="s", password="pw")
        await svc.schedule(1)
        # 手动把缓存置为过期，并把最近拉取时间设为刚刚 → 冷却期内应返回旧值
        svc._cache[1]["schedule"] = (0.0, [{"course": "old"}])
        svc._last_fetch[1] = time.monotonic()
        stale = await svc.schedule(1)
        assert stale == [{"course": "old"}]
        assert client.schedule_calls == 1

    asyncio.run(run())


def test_upstream_unavailable_maps_503():
    svc, _, client = _service()

    class DownClient(FakeClient):
        def schedule(self, session, year, term):
            raise EduUnavailable("down")

    svc._client = DownClient()

    async def run() -> None:
        await svc.bind(user_id=1, student_no="s", password="pw")
        with pytest.raises(Exception) as exc:
            await svc.schedule(1)
        assert getattr(exc.value, "http_status", None) == 503

    asyncio.run(run())


# ---------------- 接口鉴权 ----------------


def test_edu_requires_token(client):
    resp = client.get("/api/v1/edu/status")
    assert resp.status_code == 401
    assert resp.json()["code"] == 2001


def test_edu_admin_forbidden(client, settings: Settings):
    from app.core.security import create_access_token

    token = create_access_token(settings, user_id=99, role="admin")
    resp = client.get("/api/v1/edu/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["code"] == 2002


def test_openapi_includes_edu(client):
    paths = client.get("/openapi.json").json()["paths"]
    for expected in (
        "/api/v1/edu/status",
        "/api/v1/edu/bind",
        "/api/v1/edu/schedule",
        "/api/v1/edu/grades",
        "/api/v1/edu/credits",
    ):
        assert expected in paths
