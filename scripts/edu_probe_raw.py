"""P5-01 诊断脚本：直接看正方登录三步的原始响应（不经 SDK 解析）。

用途：SDK 报 JSONDecodeError 时，确认登录页 / RSA 公钥接口到底返回了什么。
只读，不提交登录（不发送密码）。

用法：
    python edu_probe_raw.py --host zfjw.hntou.edu.cn
"""

from __future__ import annotations

import argparse

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def show(tag: str, resp: requests.Response) -> None:
    body = resp.content
    text = body.decode("utf-8", "ignore")
    print(f"\n[{tag}] {resp.request.method} {resp.url}")
    print(f"  status={resp.status_code} content-type={resp.headers.get('content-type')} bytes={len(body)}")
    print(f"  set-cookie={[c.name for c in resp.cookies]}")
    snippet = " ".join(text.split())
    print(f"  body[:200]={snippet[:200]}")
    if "csrftoken" in text:
        import re

        m = re.search(r'id="csrftoken"[^>]*value="([^"]*)"', text)
        print(f"  csrf={'found' if m else 'id-present-no-value'} value_len={len(m.group(1)) if m else 0}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="zfjw.hntou.edu.cn")
    p.add_argument("--port", type=int, default=80)
    p.add_argument("--timeout", type=float, default=15)
    args = p.parse_args()

    base = f"http://{args.host}:{args.port}/jwglxt"
    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    show("1 登录页", s.get(f"{base}/xtgl/login_slogin.html", timeout=args.timeout))
    show(
        "2 RSA公钥",
        s.get(
            f"{base}/xtgl/login_getPublicKey.html",
            params={"time": 1, "_": 1},
            timeout=args.timeout,
        ),
    )
    show("3 首页(判登录态)", s.get(f"{base}/xtgl/index_initMenu.html", timeout=args.timeout))
    print("\n完成（未发送密码、未尝试登录）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
