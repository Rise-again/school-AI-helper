#!/usr/bin/env python3
"""P9-06 每日巡检：探针、进程、磁盘、显存、配额、日志轮转。

用法（服务器）：/hy-tmp/campus/venvs/web/bin/python scripts/p9_healthcheck.py
退出码：0 全部正常；1 有告警（告警写入 stdout 与 logs/health.log）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080"
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/hy-tmp/campus"))
LOG_DIR = DATA_ROOT / "logs"
HEALTH_LOG = LOG_DIR / "health.log"
PID_DIR = DATA_ROOT / "run"

DISK_WARN = 0.80
GPU_WARN = 0.90
QUOTA_MIN = 200
LOG_ROTATE_BYTES = 100 * 1024 * 1024


def rotate_logs() -> list[str]:
    rotated = []
    for name in ("backend.log", "vllm.log", "model-service.log"):
        path = LOG_DIR / name
        if not path.is_file() or path.stat().st_size < LOG_ROTATE_BYTES:
            continue
        backup = LOG_DIR / f"{name}.1"
        shutil.copyfile(path, backup)
        with open(path, "w", encoding="utf-8"):
            pass
        rotated.append(f"{name} -> {backup.name}")
    return rotated


def check_processes() -> dict:
    result = {}
    for name, port in (("vllm", 8001), ("models", 8002), ("backend", 8080)):
        pidfile = PID_DIR / f"{name}.pid"
        alive = False
        if pidfile.is_file():
            try:
                os.kill(int(pidfile.read_text().strip()), 0)
                alive = True
            except (ValueError, ProcessLookupError, PermissionError):
                alive = False
        result[name] = "ok" if alive else f"missing (port {port})"
    return result


def main() -> int:
    warnings: list[str] = []
    report: dict = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    try:
        ready = httpx.get(BASE + "/readyz", timeout=5)
        body = ready.json()
        report["readyz"] = body
        if ready.status_code != 200:
            warnings.append(f"readyz {ready.status_code}: {body.get('components')}")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"readyz 不可达: {exc.__class__.__name__}")
        report["readyz"] = "unreachable"

    try:
        metrics = httpx.get(BASE + "/metrics", timeout=5).json()
        quota = metrics.get("search_quota", {})
        report["quota_remaining"] = quota.get("remaining")
        report["gate"] = metrics.get("chat_gate")
        lag = metrics.get("timers", {}).get("event_loop.lag_ms", {}).get("max")
        report["event_loop_lag_max_ms"] = lag
        report["rss_mb"] = metrics.get("gauges", {}).get("process.rss_mb")
        if quota.get("remaining") is not None and quota["remaining"] < QUOTA_MIN:
            warnings.append(f"AnySearch 配额余量低: {quota['remaining']}")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"metrics 不可达: {exc.__class__.__name__}")

    report["processes"] = check_processes()
    for name, status in report["processes"].items():
        if status != "ok":
            warnings.append(f"进程异常 {name}: {status}")

    disk = {}
    for path in ("/", "/hy-tmp"):
        usage = shutil.disk_usage(path)
        ratio = usage.used / usage.total
        disk[path] = {"used_gb": round(usage.used / 1024**3, 1), "total_gb": round(usage.total / 1024**3, 1), "pct": round(ratio * 100, 1)}
        if ratio >= DISK_WARN:
            warnings.append(f"磁盘 {path} 使用率 {ratio*100:.1f}%")
    report["disk"] = disk

    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            text=True,
            timeout=10,
        ).strip()
        used, total = [int(x.strip()) for x in out.split(",")[:2]]
        report["gpu"] = {"used_mib": used, "total_mib": total, "pct": round(used / total * 100, 1)}
        if used / total >= GPU_WARN:
            warnings.append(f"显存使用率 {used/total*100:.1f}%")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"nvidia-smi 失败: {exc.__class__.__name__}")

    rotated = rotate_logs()
    if rotated:
        report["log_rotated"] = rotated

    report["warnings"] = warnings
    report["status"] = "ok" if not warnings else "warn"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(HEALTH_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not warnings else 1


if __name__ == "__main__":
    raise SystemExit(main())
