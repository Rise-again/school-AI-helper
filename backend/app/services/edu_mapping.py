"""教务数据的纯映射逻辑（不依赖数据库与异步框架）。

单独成文件的原因：本地验证脚本可以只导入这里 + 适配层，
不需要拉起 aiomysql / FastAPI 整套后端。
"""

from __future__ import annotations

from datetime import date
from typing import Any

_WEEKDAY_TEXT = {
    "星期一": 1, "星期二": 2, "星期三": 3, "星期四": 4,
    "星期五": 5, "星期六": 6, "星期日": 7, "星期天": 7,
}
_PASS_TEXT = {"合格", "优秀", "良好", "中等", "及格", "通过", "免修"}
_FAIL_TEXT = {"不合格", "不及格", "缺考", "旷考", "作弊", "零分", "0"}


def current_term(today: date | None = None) -> tuple[int, int]:
    """返回 (学年起始年, 学期)。8 月及以后为秋季学期 1，否则为春季学期 2。"""
    day = today or date.today()
    return (day.year, 1) if day.month >= 8 else (day.year - 1, 2)


def term_label(year: int, term: int) -> str:
    return f"{year}-{year + 1}-{term}"


def parse_term_label(label: str) -> tuple[int, int] | None:
    parts = (label or "").strip().split("-")
    if len(parts) != 3:
        return None
    try:
        year, end, term = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if end != year + 1 or term not in (1, 2):
        return None
    return year, term


def _sections(text: str) -> list[int]:
    """'1-2' → [1,2]；'3' → [3]。"""
    raw = (text or "").replace("节", "").strip()
    if not raw:
        return []
    if "-" in raw:
        start, _, end = raw.partition("-")
        try:
            return list(range(int(start), int(end) + 1))
        except ValueError:
            return []
    try:
        return [int(raw)]
    except ValueError:
        return []


def map_schedule(raw: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for course in raw.get("course_list") or []:
        if not isinstance(course, dict):
            continue
        day = str(course.get("week_day") or "").strip()
        try:
            weekday = int(day)
        except ValueError:
            weekday = _WEEKDAY_TEXT.get(str(course.get("week_day_text") or "").strip(), 0)
        sections = _sections(str(course.get("section") or course.get("jcs") or ""))
        items.append(
            {
                "weekday": weekday,
                "sections": sections,
                "course": str(course.get("course") or "").strip(),
                "teacher": (str(course.get("teacher") or "").strip() or None),
                "location": (str(course.get("place") or "").strip() or None),
                "weeks": (str(course.get("weeks_text") or "").strip() or None),
            }
        )
    return items


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def map_score_items(raw: dict[str, Any], label: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in raw.values():
        if not isinstance(item, dict):
            continue
        course = str(item.get("course_name") or "").strip()
        if not course:
            continue
        score = item.get("exam_result")
        if score in (None, ""):
            score = item.get("exam_score")
        gpa = _to_float(item.get("grade_point"))
        items.append(
            {
                "course": course,
                "credit": _to_float(item.get("credit")) or 0.0,
                "score": str(score if score is not None else "—"),
                "gpa": gpa,
                "term": label,
                # 内部字段：判定是否计入已修学分
                "_nature": str(item.get("course_nature") or "其他").strip(),
            }
        )
    return items


def _is_passed(item: dict[str, Any]) -> bool:
    text = str(item.get("score") or "").strip()
    if text in _FAIL_TEXT:
        return False
    if text in _PASS_TEXT:
        return True
    number = _to_float(text)
    if number is not None:
        return number >= 60
    # 文字成绩且没有明确判定时，有绩点即视为通过
    return item.get("gpa") is not None


def aggregate_credits(items: list[dict[str, Any]]) -> dict[str, Any]:
    earned_total = 0.0
    weighted = 0.0
    gpa_credits = 0.0
    categories: dict[str, float] = {}
    for item in items:
        credit = float(item.get("credit") or 0)
        gpa = item.get("gpa")
        if gpa is not None and credit > 0:
            weighted += gpa * credit
            gpa_credits += credit
        if _is_passed(item):
            earned_total += credit
            name = str(item.get("_nature") or "其他")
            categories[name] = categories.get(name, 0.0) + credit
    return {
        "required": 0.0,  # 培养方案不在教务接口里，按用例 UC-S5 只显示已修并说明
        "earned": round(earned_total, 1),
        "gpa": round(weighted / gpa_credits, 2) if gpa_credits else 0.0,
        "categories": [
            {"name": name, "required": 0.0, "earned": round(value, 1)}
            for name, value in sorted(categories.items(), key=lambda kv: kv[1], reverse=True)
        ],
    }


def public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if not k.startswith("_")}
