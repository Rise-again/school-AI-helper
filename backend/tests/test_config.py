"""配置模块测试：校验必须"缺了就起不来"，而不是默默用默认值。"""

from __future__ import annotations

import pytest

from app.core.config import Settings

BASE_ENV = {
    "MYSQL_USER": "root",
    "MYSQL_PASSWORD": "db-pass",
    "JWT_SECRET": "0123456789abcdef0123456789abcdef",
    "LLM_BASE_URL": "http://10.0.0.1:8001/v1",
    "EMBED_BASE_URL": "http://10.0.0.1:8002",
    "RERANK_BASE_URL": "http://10.0.0.1:8002",
    "OCR_BASE_URL": "http://10.0.0.1:8002",
}


def make_env(**overrides: str) -> dict[str, str]:
    env = dict(BASE_ENV)
    env.update(overrides)
    return env


def test_valid_config_loads(tmp_path):
    settings = Settings.from_env(env_file=tmp_path / "absent.env", environ=make_env())
    assert settings.app_env == "dev"
    assert settings.jwt_alg == "HS256"
    assert settings.llm_chat_url == "http://10.0.0.1:8001/v1/chat/completions"
    assert settings.rag_top_n <= settings.rag_top_k
    assert settings.is_prod is False


def test_missing_required_reports_readable_error(tmp_path):
    env = make_env()
    del env["MYSQL_USER"]
    with pytest.raises(RuntimeError) as exc:
        Settings.from_env(env_file=tmp_path / "absent.env", environ=env)
    assert "MYSQL_USER" in str(exc.value)  # 报错显示 .env 里的变量名，方便直接改
    assert "配置校验失败" in str(exc.value)


def test_placeholder_secret_rejected(tmp_path):
    with pytest.raises(RuntimeError) as exc:
        Settings.from_env(
            env_file=tmp_path / "absent.env",
            environ=make_env(JWT_SECRET="请替换为至少32位的随机字符串"),
        )
    assert "JWT_SECRET" in str(exc.value)


def test_short_secret_rejected(tmp_path):
    with pytest.raises(RuntimeError):
        Settings.from_env(env_file=tmp_path / "absent.env", environ=make_env(JWT_SECRET="short"))


def test_top_n_cannot_exceed_top_k(tmp_path):
    with pytest.raises(RuntimeError) as exc:
        Settings.from_env(
            env_file=tmp_path / "absent.env",
            environ=make_env(RAG_TOP_K="5", RAG_TOP_N="10"),
        )
    assert "RAG_TOP_N" in str(exc.value)


def test_non_http_endpoint_rejected(tmp_path):
    with pytest.raises(RuntimeError):
        Settings.from_env(env_file=tmp_path / "absent.env", environ=make_env(LLM_BASE_URL="10.0.0.1:8001"))


def test_env_file_is_loaded_and_os_environ_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{k}={v}" for k, v in BASE_ENV.items()) + "\nAPP_ENV=prod\n",
        encoding="utf-8",
    )
    settings = Settings.from_env(env_file=env_file, environ={"APP_ENV": "dev"})
    assert settings.app_env == "dev"  # 环境变量优先于 .env


def test_unknown_key_in_env_file_ignored(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{k}={v}" for k, v in BASE_ENV.items()) + "\nSOME_UNRELATED=1\n",
        encoding="utf-8",
    )
    assert Settings.from_env(env_file=env_file, environ={}).app_env == "dev"
