"""P5-01 教务连通性探测（只读）。

登录正方教务 → 会话检查 → 个人信息 → 课表 → 成绩，打印结构摘要，
用于确认学期参数与 SDK 返回结构，再据此实现对适配层。

用法（服务器上，school-sdk 已安装）：
    EDU_PASSWORD='***' python scripts/edu_probe.py --account 20250001 --year 2026 --term 1

密码只从环境变量或交互输入读取，不落盘、不打印、不进 shell 历史。
本脚本不做任何写操作。
"""

from __future__ import annotations

import argparse
import dataclasses
import faulthandler
import logging
import os
import sys
from datetime import date
from getpass import getpass
from typing import Any

# 默认静音（SDK 日志可能带请求细节）；--debug 时打开 requests 级日志定位卡点
logging.disable(logging.CRITICAL)


def default_year_term() -> tuple[int, int]:
    """按自然月推断学年：8 月及以后为秋季学期（term=1），否则为春季（term=2）。"""
    today = date.today()
    if today.month >= 8:
        return today.year, 1
    return today.year - 1, 2


def summarize(obj: Any, depth: int = 0, max_items: int = 3) -> str:
    """把 SDK 返回值压成可读摘要：类型 + 字段名 + 少量样例（截断）。"""
    pad = "  " * depth
    if obj is None:
        return f"{pad}None"
    if dataclasses.is_dataclass(obj):
        fields = [f.name for f in dataclasses.fields(obj)]
        return f"{pad}{type(obj).__module__}.{type(obj).__name__} fields={fields}"
    if isinstance(obj, dict):
        lines = [f"{pad}{type(obj).__name__} keys={list(obj.keys())[:30]}"]
        for key, value in list(obj.items())[:max_items]:
            lines.append(f"{pad}  [{key}] {short(value)}")
        return "\n".join(lines)
    if isinstance(obj, (list, tuple)):
        lines = [f"{pad}{type(obj).__name__} len={len(obj)}"]
        for item in list(obj)[:max_items]:
            lines.append(summarize(item, depth + 1, max_items=2))
        return "\n".join(lines)
    attrs = [a for a in vars(obj)] if hasattr(obj, "__dict__") else []
    if attrs:
        lines = [f"{pad}{type(obj).__module__}.{type(obj).__name__} attrs={attrs[:30]}"]
        for name in attrs[:max_items]:
            lines.append(f"{pad}  .{name} = {short(getattr(obj, name, None))}")
        return "\n".join(lines)
    return f"{pad}{short(obj)}"


def short(value: Any, limit: int = 60) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "…"


def step(title: str) -> None:
    print(f"\n===== {title} =====", flush=True)


def endpoints_with_base(base_path: str) -> dict[str, Any]:
    """学校教务挂在 /jwglxt 下，SDK 内置端点没有这个前缀，这里统一补上。"""
    from school_sdk.config import URL_ENDPOINT

    def fix(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: fix(v) for k, v in value.items()}
        if isinstance(value, str) and value.startswith("/"):
            return base_path + value
        return value

    return {k: fix(v) for k, v in URL_ENDPOINT.items()}


def main() -> int:
    year, term = default_year_term()
    parser = argparse.ArgumentParser(description="正方教务连通性探测（只读）")
    parser.add_argument("--account", default=os.getenv("EDU_ACCOUNT", ""), help="学号")
    parser.add_argument("--year", type=int, default=year, help=f"学年（默认 {year}）")
    parser.add_argument("--term", type=int, default=term, help=f"学期 1/2（默认 {term}）")
    parser.add_argument("--host", default=os.getenv("EDU_HOST", "zfjw.hntou.edu.cn"))
    parser.add_argument("--port", type=int, default=int(os.getenv("EDU_PORT", "80")))
    parser.add_argument("--ssl", action="store_true", default=os.getenv("EDU_SSL", "false").lower() == "true")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("EDU_TIMEOUT_S", "15")))
    parser.add_argument("--debug", action="store_true", help="打开请求日志，并在卡住 45 秒后打印调用栈")
    parser.add_argument("--dump", action="store_true", help="打印课表首条与成绩前 3 条的完整 JSON，用于确认字段结构")
    parser.add_argument(
        "--base-path",
        default=os.getenv("EDU_BASE_PATH", "/jwglxt"),
        help="教务系统路径前缀（默认 /jwglxt）",
    )
    args = parser.parse_args()

    if args.debug:
        logging.disable(logging.NOTSET)
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(message)s")
        # 卡住 45 秒后把当前调用栈打出来，定位到底停在哪个请求
        faulthandler.dump_traceback_later(45, repeat=True)

    account = args.account or input("学号: ").strip()
    password = os.getenv("EDU_PASSWORD") or getpass("教务密码（不回显）: ")
    if not account or not password:
        print("缺少学号或密码", file=sys.stderr)
        return 2

    from school_sdk import SchoolClient  # 延迟导入，未安装时给出明确提示

    step(f"连接 {args.host}:{args.port}（ssl={args.ssl}）")
    client = SchoolClient(
        host=args.host,
        port=args.port,
        ssl=args.ssl,
        exist_verify=False,  # 用户已确认学校无验证码
        retry=2,
        timeout=args.timeout,
        url_endpoints=endpoints_with_base(args.base_path),
    )
    print("SchoolClient 就绪，参数字典:", summarize(getattr(client, "__dict__", {})))

    step("登录")
    user = client.user_login(account, password)
    print(f"登录成功，user 类型: {type(user).__module__}.{type(user).__name__}")

    step("会话检查 check_session()")
    print(short(user.check_session(), 120))

    step("个人信息 get_info()")
    info = user.get_info()
    print(summarize(info))

    step(f"课表 get_schedule(year={args.year}, term={args.term})")
    schedule = user.get_schedule(year=args.year, term=args.term)
    print(summarize(schedule, max_items=5))
    if args.dump and isinstance(schedule, dict) and schedule.get("course_list"):
        import json

        print("首条课程完整 JSON:")
        print(json.dumps(schedule["course_list"][0], ensure_ascii=False, indent=2))

    step(f"成绩 get_score(year={args.year}, term={args.term})")
    score = user.get_score(year=args.year, term=args.term)
    print(summarize(score, max_items=5))
    if args.dump and isinstance(score, dict) and score:
        import json

        print("成绩前 3 条完整 JSON:")
        print(json.dumps(list(score.values())[:3], ensure_ascii=False, indent=2))

    step("完成")
    print(f"学年参数：year={args.year}, term={args.term}（按自然月推断，可 --year/--term 覆盖）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - 探测脚本要给出可读失败原因
        print(f"\n探测失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
