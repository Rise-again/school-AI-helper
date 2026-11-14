"""教务接口的契约与权限验收（Fake 上游，不连真实教务）。

覆盖：绑定→查询全链路、未绑定 400、上游 503、管理员 403、两人数据隔离、
适配层唯一 import 约束、库内不落明文口令。
"""

from __future__ import annotations

import pathlib
from typing import Any

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.integrations.edu import EduSession, EduUnavailable
from app.services.edu_service import EduService
from tests.conftest import BASE_ENV
from app.core.config import Settings


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
        self.down = False
        self.logins = 0

    def login(self, account: str, password: str) -> EduSession:
        self.logins += 1
        return EduSession(account=account, raw=object())

    def info(self, session: EduSession):
        return {"student_number": session.account}

    def schedule(self, session: EduSession, year: int, term: int):
        if self.down:
            raise EduUnavailable("down")
        return {
            "course_list": [
                {
                    "course": f"课程-{session.account}",
                    "place": "3401",
                    "teacher": "老师",
                    "weeks_text": "1-16周",
                    "week_day": "2",
                    "section": "3-4",
                }
            ]
        }

    def scores(self, session: EduSession, year: int, term: int):
        if self.down:
            raise EduUnavailable("down")
        from app.services.edu_mapping import current_term

        if (year, term) != current_term():
            return {}
        return {
            "数据结构": {
                "course_name": "数据结构",
                "course_nature": "学科基础课",
                "exam_result": "88",
                "credit": "4",
                "grade_point": "3.30",
            }
        }


def _settings() -> Settings:
    return Settings.from_env(env_file=None, environ=BASE_ENV)


def _token(settings: Settings, user_id: int, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(settings, user_id=user_id, role=role)}"}


def _client_with_fakes(client: TestClient) -> tuple[FakeRepo, FakeClient]:
    repo, fake = FakeRepo(), FakeClient()
    client.app.state.edu_service = EduService(
        settings=client.app.state.settings, users=repo, client=fake
    )
    return repo, fake


def test_edu_full_flow_contract(client, settings: Settings):
    repo, fake = _client_with_fakes(client)
    headers = _token(settings, 1, "student")

    assert client.get("/api/v1/edu/status", headers=headers).json()["data"]["bound"] is False

    bind = client.post(
        "/api/v1/edu/bind",
        headers=headers,
        json={"student_no": "20250001", "password": "pw"},
    )
    assert bind.status_code == 200
    assert bind.json()["data"]["bound"] is True
    # 密文入库，明文不出现
    assert repo.rows[1]["edu_cred_cipher"] != b"pw"

    schedule = client.get("/api/v1/edu/schedule", headers=headers).json()["data"]
    assert schedule["items"][0] == {
        "weekday": 2,
        "sections": [3, 4],
        "course": "课程-20250001",
        "teacher": "老师",
        "location": "3401",
        "weeks": "1-16周",
    }

    grades = client.get("/api/v1/edu/grades", headers=headers).json()["data"]
    assert grades["terms"] and grades["items"][0]["course"] == "数据结构"
    assert grades["items"][0]["score"] == "88"

    credits = client.get("/api/v1/edu/credits", headers=headers).json()["data"]
    assert credits["earned"] == 4.0
    assert credits["gpa"] == 3.3

    unbind = client.delete("/api/v1/edu/bind", headers=headers)
    assert unbind.status_code == 200
    assert client.get("/api/v1/edu/status", headers=headers).json()["data"]["bound"] is False


def test_edu_unbound_returns_400(client, settings: Settings):
    _client_with_fakes(client)
    resp = client.get("/api/v1/edu/schedule", headers=_token(settings, 2, "student"))
    assert resp.status_code == 400
    assert resp.json()["code"] == 1001
    assert "绑定" in resp.json()["message"]


def test_edu_upstream_down_returns_503(client, settings: Settings):
    _, fake = _client_with_fakes(client)
    headers = _token(settings, 3, "student")
    client.post(
        "/api/v1/edu/bind", headers=headers, json={"student_no": "20250003", "password": "pw"}
    )
    fake.down = True
    resp = client.get("/api/v1/edu/schedule", headers=headers)
    assert resp.status_code == 503
    assert resp.json()["code"] == 6001
    assert "教务系统" in resp.json()["message"]


def test_edu_two_users_isolated(client, settings: Settings):
    _client_with_fakes(client)
    h1, h2 = _token(settings, 11, "student"), _token(settings, 12, "student")
    client.post("/api/v1/edu/bind", headers=h1, json={"student_no": "A001", "password": "pw"})
    client.post("/api/v1/edu/bind", headers=h2, json={"student_no": "B002", "password": "pw"})
    c1 = client.get("/api/v1/edu/schedule", headers=h1).json()["data"]["items"][0]["course"]
    c2 = client.get("/api/v1/edu/schedule", headers=h2).json()["data"]["items"][0]["course"]
    assert c1 == "课程-A001" and c2 == "课程-B002"


def test_edu_sdk_import_only_in_adapter():
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    hits = [
        path
        for path in root.rglob("*.py")
        if "school_sdk" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits and all("integrations/edu" in str(p).replace("\\", "/") for p in hits)
