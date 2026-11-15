#!/usr/bin/env python3
"""P8-03 E2E 主路径（Playwright）。

运行（服务器上）：
    PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers /tmp/pwvenv/bin/python scripts/e2e_p8.py

覆盖：
1. 访客问答（知识库可答）与库外拒答；
2. 管理员上传 → 解析完成 → 检索命中 → 删除清理；
3. 学生教务：按 D-21 等校方网络恢复，脚本标记 blocked，不伪造通过。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
ADMIN = ("admin", "Admin@12345")
SHOT_DIR = Path("docs/p8-e2e-shots")
VIDEO_DIR = Path("docs/p8-e2e-videos")


def wait_text(page, needle: str, timeout: float = 45) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if needle in page.inner_text("body"):
            return True
        page.wait_for_timeout(500)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    marker = "蓝色风车8848"
    upload_name = f"P8-E2E-{int(time.time())}.txt"
    upload_path = Path("/tmp") / upload_name
    upload_path.write_text(
        ("P8 端到端测试文档。测试标记：" + marker + "。该文件由 E2E 脚本临时上传，验证后会删除。\n") * 8,
        encoding="utf-8",
    )

    report: dict = {"base": args.base, "guest_answer": False, "guest_refusal": False, "admin_upload": False, "admin_search": False, "cleanup": False, "student_edu": "blocked_external", "errors": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

        try:
            # ---------- 1. 访客问答 ----------
            page.goto(args.base + "/#/guest", wait_until="networkidle", timeout=30000)
            page.locator("textarea").fill("勤工助学的报酬标准是什么？")
            page.get_by_role("button", name="发送").click()
            report["guest_answer"] = wait_text(page, "报酬", 60) and wait_text(page, "参考：", 20)
            page.screenshot(path=str(SHOT_DIR / "01-guest-answer.png"), full_page=False)

            page.locator("textarea").fill("火星校区的食堂在哪里？")
            page.get_by_role("button", name="发送").click()
            report["guest_refusal"] = wait_text(page, "没有在知识库", 60) or wait_text(page, "不做推测", 5)
            page.screenshot(path=str(SHOT_DIR / "02-guest-refusal.png"))

            # ---------- 2. 管理员上传 -> 检索 -> 删除 ----------
            page.goto(args.base + "/#/login", wait_until="networkidle", timeout=30000)
            page.get_by_placeholder("学号或管理员账号").fill(ADMIN[0])
            page.get_by_placeholder("请输入密码").fill(ADMIN[1])
            page.get_by_role("button", name="登录").click()
            page.wait_for_timeout(2000)
            page.goto(args.base + "/#/knowledge", wait_until="networkidle", timeout=30000)

            page.locator('input[type="file"]').set_input_files(str(upload_path))
            report["admin_upload"] = wait_text(page, upload_name, 90)
            page.screenshot(path=str(SHOT_DIR / "03-admin-uploaded.png"))

            token = page.evaluate("localStorage.getItem('access_token')")
            headers = {"Authorization": f"Bearer {token}"}

            def api(path: str, params: dict | None = None):
                resp = page.request.get(args.base + path, headers=headers, params=params)
                return resp.json()

            file_id = None
            deadline = time.time() + 150
            while time.time() < deadline:
                data = api("/api/v1/kb/files?size=100")["data"]
                row = next((item for item in data["items"] if item["filename"] == upload_name), None)
                if row:
                    file_id = row["id"]
                    if row["parse_status"] == "success":
                        break
                time.sleep(3)
            report["admin_upload"] = report["admin_upload"] and file_id is not None

            # 检索必须命中刚上传的文档（用完整短语，避免极短生僻词检索的噪声）
            time.sleep(1)
            result = api("/api/v1/rag/search", {"q": "P8 端到端测试文档 测试标记 " + marker})
            report["admin_search"] = result["data"]["count"] > 0
            report["search_count"] = result["data"]["count"]
            page.reload(wait_until="networkidle")
            page.screenshot(path=str(SHOT_DIR / "04-admin-search.png"))

            # 清理：删除临时文件与向量
            if file_id:
                page.request.delete(args.base + f"/api/v1/kb/files/{file_id}", headers=headers)
                time.sleep(1)
                files = api("/api/v1/kb/files?size=100")["data"]["items"]
                report["cleanup"] = all(item["filename"] != upload_name for item in files)
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"{type(exc).__name__}: {exc}")
            page.screenshot(path=str(SHOT_DIR / "99-error.png"))
        finally:
            report["console_errors"] = console_errors[:10]
            context.close()
            video = page.video.path() if page.video else None
            report["video"] = str(video) if video else None
            browser.close()

    upload_path.unlink(missing_ok=True)
    report["passed"] = all(
        [report["guest_answer"], report["guest_refusal"], report["admin_upload"], report["admin_search"], report["cleanup"]]
    ) and not report["errors"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
