"""接口契约：信封结构、鉴权、校验失败、探针。

这些用例不依赖 MySQL，可以随时跑。
"""

from __future__ import annotations


def _assert_envelope(body: dict) -> None:
    assert set(body) == {"code", "message", "data", "trace_id"}
    assert isinstance(body["trace_id"], str) and body["trace_id"]


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers["X-Trace-Id"]


def test_readyz_reports_degraded_without_mysql(client):
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert "mysql" in body["components"]


def test_me_requires_token(client):
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401
    body = resp.json()
    _assert_envelope(body)
    assert body["code"] == 2001


def test_me_rejects_bad_token(client):
    resp = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 2001


def test_login_validation_envelope(client):
    resp = client.post("/api/v1/auth/login", json={"username": "1", "password": ""})
    assert resp.status_code == 422
    body = resp.json()
    _assert_envelope(body)
    assert body["code"] == 4001


def test_conversations_requires_auth(client):
    resp = client.get("/api/v1/conversations")
    assert resp.status_code == 401
    assert resp.json()["code"] == 2001


def test_unknown_route_uses_envelope(client):
    resp = client.get("/api/v1/not-exist")
    assert resp.status_code == 404
    body = resp.json()
    _assert_envelope(body)
    assert body["code"] == 3001


def test_openapi_is_available(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    for expected in ("/api/v1/auth/login", "/api/v1/me", "/api/v1/conversations"):
        assert expected in paths


def test_cors_preflight_allows_frontend_origin(client):
    resp = client.options(
        "/api/v1/me",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
