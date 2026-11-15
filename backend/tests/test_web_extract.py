"""网页正文提取的单元测试。"""

from __future__ import annotations

from app.integrations.anysearch import AnySearchClient


def test_extract_text_drops_nav_and_script():
    html = """
    <html><head><script>var x=1;</script><style>.a{}</style></head>
    <body><nav>首页 新闻</nav><div>2026年国庆放假通知：10月1日至7日放假。</div>
    <footer>CopyRight 2022 版权所有</footer></body></html>
    """
    text = AnySearchClient.extract_text(html)
    assert "国庆放假通知" in text
    assert "var x" not in text and "首页" not in text and "CopyRight" not in text
