"""联网证据时效性检查的单元测试。"""

from __future__ import annotations

from datetime import date

from app.rag.freshness import is_stale, latest_year, page_years


def test_page_years_extracts_grades_and_dates():
    assert page_years("2023级学生国防教育暨军训总结大会", "2023年9月19日") == {2023}
    assert page_years("通知发布时间：2026-09-01", "https://x/2025/10/a.html") == {2026, 2025}
    assert page_years("没有年份的正文") == set()


def test_latest_year_picks_max():
    assert latest_year("2023级", "2026 年更新") == 2026
    assert latest_year("") is None


def test_footer_years_are_ignored():
    # 页脚版权年份不能把新页面判成过时
    text = "2026年国庆放假安排如下…… CopyRight 2022. HNTOU.EDU.CN. All Rights Reserved. 琼ICP备18001963号"
    assert page_years(text) == {2026}
    assert not is_stale(title="国庆放假通知", content=text, today=date(2026, 11, 15))


def test_stale_threshold():
    today = date(2026, 11, 15)
    assert is_stale(title="2023级军训总结", content="2023年9月", today=today, max_age_years=2)
    assert not is_stale(title="2025级军训安排", content="2025年9月", today=today, max_age_years=2)
    assert not is_stale(title="无日期页面", content="正文内容", today=today, max_age_years=2)
    assert is_stale(title="", content="", url="https://www.hntou.edu.cn/2023/0919/a.html", today=today)
    # 未来年份（如校历里的 2027）不算过时
    assert not is_stale(title="2027 校历", content="2027年3月", today=today)
