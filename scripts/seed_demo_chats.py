#!/usr/bin/env python3
"""P9-05：重置三角色演示会话（可重复执行）。

- 先登录 admin / 20230001 / 20230002，各自删除现有会话（软删除）；
- 每个账号创建 3 个真实问答会话（走生产 SSE，带引用与轨迹），供演示。
- 访客不落库，演示脚本现场提问。

用法（服务器）：/hy-tmp/campus/venvs/web/bin/python scripts/seed_demo_chats.py
"""

from __future__ import annotations

import json
import time

import httpx

BASE = "http://127.0.0.1:8080"
ACCOUNTS = {
    "admin": ("admin", "Admin@12345"),
    "20230001": ("20230001", "Student@123"),
    "20230002": ("20230002", "Student@123"),
}
QUESTIONS = {
    "admin": [
        "学校有哪些勤工助学岗位？怎么报名？",
        "国家助学金的资助标准是多少？",
        "国家励志奖学金的申请条件是什么？",
    ],
    "20230001": [
        "勤工助学的报酬标准是多少？",
        "家庭经济困难学生认定需要准备哪些材料？",
        "学费减免怎么申请？能减多少？",
    ],
    "20230002": [
        "转专业有什么条件和流程？",
        "绿色通道怎么办理？",
        "少数民族学生学费补助能补多少？",
    ],
}


def login(client: httpx.Client, username: str, password: str) -> str:
    resp = client.post(BASE + "/api/v1/auth/login", json={"username": username, "password": password})
    resp.raise_for_status()
    return resp.json()["data"]["access_token"]


def clear_conversations(client: httpx.Client, token: str) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    items = client.get(BASE + "/api/v1/conversations", params={"size": 100}, headers=headers).json()["data"]["items"]
    for item in items:
        client.delete(BASE + f"/api/v1/conversations/{item['id']}", headers=headers)
    return len(items)


def ask(client: httpx.Client, token: str, conversation_id: int, question: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    answer = ""
    with client.stream(
        "POST",
        BASE + f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": question},
        headers=headers,
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        event = ""
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except ValueError:
                    continue
                if event == "delta":
                    answer += data.get("text", "")
                elif event == "replace":
                    answer = data.get("text", "")
    return answer


def main() -> int:
    with httpx.Client(timeout=120) as client:
        for username, (login_name, password) in ACCOUNTS.items():
            token = login(client, login_name, password)
            headers = {"Authorization": f"Bearer {token}"}
            removed = clear_conversations(client, token)
            print(f"{username}: 清理 {removed} 个旧会话")
            for question in QUESTIONS[username]:
                conv = client.post(BASE + "/api/v1/conversations", json={"title": question}, headers=headers).json()["data"]
                answer = ask(client, token, conv["id"], question)
                print(f"  [{username}] {question[:20]} → {len(answer)} 字")
                time.sleep(0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
