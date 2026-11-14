"""教务查询业务层。

职责：
- 绑定/解绑教务账号，口令以 AES-GCM 密文存库；
- 维护进程内会话（单 worker，重启或失效后自动重登一次）；
- 课表/成绩/学分的取数，带 TTL 缓存与"刷新级"冷却；
- 给对话节点提供确定性的文字回答（不经过大模型）。

不做的事：任何写操作、任何他人数据。
纯映射逻辑在 `edu_mapping.py`，本地验证脚本可单独复用。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from app.core.config import Settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.errors import BadRequest, EduUnavailable
from app.core.logging import log_fields
from app.integrations.edu import (
    EduAuthError,
    EduClient,
    EduSession,
    EduSessionExpired,
    EduUnavailable as EduUpstreamUnavailable,
)
from app.repositories.users import UserRepository
from app.services.edu_mapping import (
    aggregate_credits,
    current_term,
    map_schedule,
    map_score_items,
    parse_term_label,
    public_item,
    term_label,
)

__all__ = [
    "EduNotBound",
    "EduService",
    "aggregate_credits",
    "current_term",
    "map_schedule",
    "map_score_items",
    "parse_term_label",
    "term_label",
]

logger = logging.getLogger("campus.edu")


class EduNotBound(BadRequest):
    default_message = "尚未绑定教务账号"


class EduService:
    def __init__(self, *, settings: Settings, users: UserRepository, client: EduClient) -> None:
        self._settings = settings
        self._users = users
        self._client = client
        self._sessions: dict[int, EduSession] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._cache: dict[int, dict[str, tuple[float, Any]]] = {}
        self._last_fetch: dict[int, float] = {}

    # ---------------- 基础 ----------------
    def _lock(self, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    async def _binding(self, user_id: int) -> dict[str, Any]:
        row = await self._users.get_edu_binding(user_id)
        if not row or not row.get("edu_username") or not row.get("edu_cred_cipher"):
            raise EduNotBound()
        return row

    async def _session(self, user_id: int, *, force: bool = False) -> EduSession:
        if not force and (session := self._sessions.get(user_id)) is not None:
            return session
        row = await self._binding(user_id)
        try:
            password = decrypt_secret(self._settings, user_id, row.get("edu_cred_cipher"))
        except ValueError as exc:
            raise BadRequest("教务绑定信息已损坏，请重新绑定") from exc
        try:
            session = await asyncio.to_thread(
                self._client.login, str(row["edu_username"]), password
            )
        except EduAuthError as exc:
            raise BadRequest("教务密码已变更或账号被锁定，请重新绑定") from exc
        except EduUpstreamUnavailable as exc:
            raise EduUnavailable("教务系统暂时无法访问") from exc
        self._sessions[user_id] = session
        return session

    async def _call(self, user_id: int, fn: Callable[[EduSession], Any], *, action: str) -> Any:
        """串行化同一用户的上游调用；会话失效时重登一次再试。"""
        async with self._lock(user_id):
            session = await self._session(user_id)
            try:
                return await asyncio.to_thread(fn, session)
            except EduSessionExpired:
                logger.info("edu_session_expired", extra=log_fields(user_id=user_id, action=action))
                self._sessions.pop(user_id, None)
                session = await self._session(user_id, force=True)
                try:
                    return await asyncio.to_thread(fn, session)
                except EduUpstreamUnavailable as exc:
                    raise EduUnavailable("教务系统暂时无法访问") from exc
            except EduUpstreamUnavailable as exc:
                raise EduUnavailable("教务系统暂时无法访问") from exc

    # ---------------- 绑定 ----------------
    async def bind(self, *, user_id: int, student_no: str, password: str) -> dict[str, Any]:
        student_no = student_no.strip()
        if not student_no or not password:
            raise BadRequest("学号与教务密码不能为空")
        try:
            session = await asyncio.to_thread(self._client.login, student_no, password)
        except EduAuthError as exc:
            raise BadRequest("教务账号或密码不正确") from exc
        except EduUpstreamUnavailable as exc:
            raise EduUnavailable("教务系统暂时无法访问，请稍后再试") from exc
        cipher = encrypt_secret(self._settings, user_id, password)
        try:
            await self._users.save_edu_binding(
                user_id=user_id,
                student_no=student_no,
                edu_username=student_no,
                cred_cipher=cipher,
            )
        except Exception as exc:  # noqa: BLE001 - 唯一键冲突等给出可读提示
            if "Duplicate entry" in str(exc):
                raise BadRequest("该学号已绑定其他账号") from exc
            raise
        self._sessions[user_id] = session
        self._cache.pop(user_id, None)
        logger.info("edu_bound", extra=log_fields(user_id=user_id, student_no=student_no))
        return await self.status(user_id)

    async def unbind(self, user_id: int) -> None:
        await self._users.clear_edu_binding(user_id)
        self._sessions.pop(user_id, None)
        self._cache.pop(user_id, None)
        self._last_fetch.pop(user_id, None)
        logger.info("edu_unbound", extra=log_fields(user_id=user_id))

    async def status(self, user_id: int) -> dict[str, Any]:
        row = await self._users.get_edu_binding(user_id)
        bound = bool(row and row.get("edu_username") and row.get("edu_cred_cipher"))
        bound_at = row.get("edu_bound_at") if row else None
        return {
            "bound": bound,
            "student_no": (str(row.get("edu_username")) if bound else None),
            "updated_at": bound_at.isoformat(sep=" ", timespec="seconds") if bound_at else None,
        }

    # ---------------- 取数 ----------------
    def _terms(self) -> list[tuple[int, int]]:
        year, term = current_term()
        terms: list[tuple[int, int]] = []
        for _ in range(self._settings.edu_terms_lookback):
            terms.append((year, term))
            if term == 1:
                year, term = year - 1, 2
            else:
                term = 1
        return terms

    def _cached(self, user_id: int, key: str) -> tuple[bool, Any]:
        entry = self._cache.get(user_id, {}).get(key)
        if not entry:
            return False, None
        at, value = entry
        if time.monotonic() - at > self._settings.edu_cache_ttl_s:
            return False, None
        return True, value

    def _stale(self, user_id: int, key: str) -> Any | None:
        entry = self._cache.get(user_id, {}).get(key)
        return entry[1] if entry else None

    def _store(self, user_id: int, key: str, value: Any) -> None:
        self._cache.setdefault(user_id, {})[key] = (time.monotonic(), value)

    async def _cached_fetch(
        self, user_id: int, key: str, loader: Callable[[], Awaitable[Any]]
    ) -> Any:
        fresh, value = self._cached(user_id, key)
        if fresh:
            return value
        stale = self._stale(user_id, key)
        if stale is not None:
            last = self._last_fetch.get(user_id, 0.0)
            if time.monotonic() - last < self._settings.edu_refresh_cooldown_s:
                return stale  # 冷却期内先给旧数据，避免页面三连击打穿上游
        result = await loader()
        self._store(user_id, key, result)
        self._last_fetch[user_id] = time.monotonic()
        return result

    async def _schedule_raw(self, user_id: int, year: int, term: int) -> dict[str, Any]:
        return await self._call(
            user_id, lambda session: self._client.schedule(session, year, term), action="课表"
        )

    async def _scores_raw(self, user_id: int, year: int, term: int) -> dict[str, Any]:
        return await self._call(
            user_id, lambda session: self._client.scores(session, year, term), action="成绩"
        )

    async def all_scores(self, user_id: int) -> list[dict[str, Any]]:
        """聚合最近几个学期的成绩（成绩单里只有本学期时也照样返回）。"""
        await self._binding(user_id)  # 未绑定直接 400，避免无谓请求
        items: list[dict[str, Any]] = []
        for year, term in self._terms():
            key = f"scores:{year}:{term}"

            async def loader(y: int = year, t: int = term) -> list[dict[str, Any]]:
                raw = await self._scores_raw(user_id, y, t)
                return map_score_items(raw, term_label(y, t))

            items.extend(await self._cached_fetch(user_id, key, loader))
        return items

    async def schedule(self, user_id: int) -> list[dict[str, Any]]:
        year, term = current_term()
        key = "schedule"

        async def loader() -> list[dict[str, Any]]:
            raw = await self._schedule_raw(user_id, year, term)
            return map_schedule(raw)

        return await self._cached_fetch(user_id, key, loader)

    async def grades(self, user_id: int, term: str | None = None) -> dict[str, Any]:
        items = await self.all_scores(user_id)
        labels = sorted({item["term"] for item in items}, reverse=True)
        label = term or (labels[0] if labels else term_label(*current_term()))
        selected = [public_item(i) for i in items if i["term"] == label]
        return {"terms": labels, "items": selected}

    async def credits(self, user_id: int) -> dict[str, Any]:
        return aggregate_credits(await self.all_scores(user_id))

    # ---------------- 对话用的确定性回答 ----------------
    async def chat_answer(self, user_id: int, query: str) -> str:
        """课表/成绩/学分 → 模板直出。问题与数据无关时不猜，交给调用方。"""
        if any(word in query for word in ("学分", "绩点", "GPA", "gpa")):
            data = await self.credits(user_id)
            lines = [f"你目前累计已修 {data['earned']:g} 学分，平均绩点 {data['gpa']:.2f}。"]
            if data["categories"]:
                detail = "、".join(f"{c['name']} {c['earned']:g} 学分" for c in data["categories"][:6])
                lines.append(f"按课程性质分：{detail}。")
            lines.append("毕业学分要求以培养方案为准，教务系统未提供该数据。")
            return "\n".join(lines)

        if any(word in query for word in ("成绩", "分数", "挂科")):
            data = await self.grades(user_id)
            if not data["items"]:
                return "本学期成绩还没出，教务系统暂无记录。"
            title = data["items"][0]["term"]
            rows = [f"{i['course']}：{i['score']}" for i in data["items"][:12]]
            more = "（仅列出前 12 门）" if len(data["items"]) > 12 else ""
            return f"{title} 共 {len(data['items'])} 门课程：\n" + "、".join(rows) + more

        slots = await self.schedule(user_id)
        if not slots:
            return "本学期教务系统里还没有课表数据。"
        names = {slot["course"] for slot in slots}
        return (
            f"你本学期共有 {len(names)} 门课、{len(slots)} 个上课时段。"
            "完整课表在「教务查询 → 课表」里，按节次和星期排列，可以查看每门课的地点与周次。"
        )
