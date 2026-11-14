"""P5 本地端到端验证（校园网内运行）。

为什么需要它：学校教务今天起只对校内网放行，云服务器连不上；
这个脚本在能访问教务的电脑上，用后端真实的适配层与映射逻辑
跑一遍"登录 → 课表 → 成绩 → 学分"，把结果写到 JSON 文件，
之后把文件内容贴回来即可完成联调核对。

用法（仓库根目录）：
    python scripts/edu_e2e_local.py --account 20250001
密码交互输入，不落盘。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from getpass import getpass
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.integrations.edu import (  # noqa: E402
    EduAuthError,
    EduUnavailable,
    SchoolSdkEduClient,
)
from app.services.edu_mapping import (  # noqa: E402
    aggregate_credits,
    current_term,
    map_schedule,
    map_score_items,
    term_label,
)


def _settings() -> SimpleNamespace:
    """适配层只用到 edu_* 几个字段；不拉 pydantic，脚本依赖降到最低。"""
    return SimpleNamespace(
        edu_host=os.getenv("EDU_HOST", "zfjw.hntou.edu.cn"),
        edu_port=int(os.getenv("EDU_PORT", "80")),
        edu_ssl=os.getenv("EDU_SSL", "false").lower() == "true",
        edu_base_path=os.getenv("EDU_BASE_PATH", "/jwglxt"),
        edu_timeout_s=float(os.getenv("EDU_TIMEOUT_S", "15")),
        edu_retry=int(os.getenv("EDU_RETRY", "2")),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="教务本地端到端验证")
    parser.add_argument("--account", required=True)
    parser.add_argument("--out", default="edu_e2e_result.json")
    parser.add_argument("--lookback", type=int, default=4)
    args = parser.parse_args()

    password = getpass("教务密码（不回显）: ")
    if not password:
        print("缺少密码", file=sys.stderr)
        return 2

    settings = _settings()
    client = SchoolSdkEduClient(settings)

    print("→ 登录…", flush=True)
    try:
        session = client.login(args.account, password)
    except EduAuthError as exc:
        print(f"登录失败：{exc}", file=sys.stderr)
        return 1
    except EduUnavailable as exc:
        print(f"连接失败：{exc}（确认已连校园网）", file=sys.stderr)
        return 1

    info = client.info(session)
    print(f"→ 个人信息：{info.get('name', '')} / {info.get('class_name', '')}")

    year, term = current_term()
    print(f"→ 课表 {term_label(year, term)}…", flush=True)
    schedule = map_schedule(client.schedule(session, year, term))

    print("→ 成绩（最近 %d 个学期）…" % args.lookback, flush=True)
    scores: list[dict] = []
    y, t = year, term
    for _ in range(args.lookback):
        raw = client.scores(session, y, t)
        scores.extend(map_score_items(raw, term_label(y, t)))
        if t == 1:
            y, t = y - 1, 2
        else:
            t = 1

    credits = aggregate_credits(scores)
    result = {
        "checked_at": date.today().isoformat(),
        "student": {
            "no": info.get("student_number"),
            "name": info.get("name"),
            "class": info.get("class_name"),
            "major": info.get("major"),
        },
        "schedule": schedule,
        "scores": [{k: v for k, v in s.items() if not k.startswith("_")} for s in scores],
        "credits": credits,
    }
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n课表 {len(schedule)} 个时段；成绩 {len(scores)} 条；"
          f"已修 {credits['earned']:g} 学分，平均绩点 {credits['gpa']:.2f}")
    print(f"结果已写入 {args.out}，把这个文件内容贴回来即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
