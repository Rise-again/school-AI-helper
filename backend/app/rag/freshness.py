"""联网证据的时效性检查。

只作用于 AnySearch 的网页结果，不动知识库（知识库有过期日字段，另走 effective_to）。
目的：2026 年问"新生军训"，不要把 2023 年的军训总结新闻当依据。

规则：
- 从标题、正文、URL 里提取四位年份（20xx，含"2023级"这种写法）；
- 取其中最大的年份作为"页面最新年份"；
- 若最大年份距当前年份 ≥ WEB_MAX_AGE_YEARS（默认 2 年），判定过时，剔除；
- 提取不到任何年份的页面不判过时（宁可保留，避免误杀无日期页面）。
"""

from __future__ import annotations

import re
from datetime import date

_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def page_years(*texts: str | None) -> set[int]:
    years: set[int] = set()
    for text in texts:
        if not text:
            continue
        for match in _YEAR_RE.findall(str(text)):
            year = int(match)
            if 2000 <= year <= date.today().year + 1:  # 明显不合法的年份不算
                years.add(year)
    return years


def latest_year(*texts: str | None) -> int | None:
    years = page_years(*texts)
    return max(years) if years else None


def is_stale(
    *,
    title: str | None,
    content: str | None,
    url: str | None = None,
    max_age_years: int = 2,
    today: date | None = None,
) -> bool:
    year = latest_year(title, content, url)
    if year is None:
        return False
    current = (today or date.today()).year
    return current - year >= max_age_years
