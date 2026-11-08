#!/usr/bin/env python3
"""开发环境自检（只用标准库，装依赖之前就能跑）。

用法：
    python scripts/check_env.py

输出每项 OK / WARN / FAIL；存在 FAIL 时退出码为 1。
模型服务相关项默认是 WARN：本地不跑模型，云端没开机属于正常状态。
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "backend" / ".env"

OK, WARN, FAIL = "OK", "WARN", "FAIL"
results: list[tuple[str, str, str]] = []


def add(level: str, item: str, detail: str = "") -> None:
    results.append((level, item, detail))


def _load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def check_python() -> None:
    major, minor = sys.version_info[:2]
    ver = f"{major}.{minor}.{sys.version_info[2]}"
    if (major, minor) == (3, 10):
        add(OK, "Python", ver)
    elif (major, minor) >= (3, 10):
        add(WARN, "Python", f"{ver}（要求 3.10.x，版本不一致可能装不上轮子）")
    else:
        add(FAIL, "Python", f"{ver}（要求 3.10+）")


def check_node() -> None:
    try:
        out = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        add(WARN, "Node", "未安装（P6 前端才需要）")
        return
    try:
        major = int(out.lstrip("v").split(".")[0])
    except ValueError:
        add(WARN, "Node", f"版本解析失败：{out}")
        return
    add(OK if major >= 18 else FAIL, "Node", f"{out}（要求 >=18）")


def check_env_file() -> dict[str, str]:
    if not ENV_FILE.is_file():
        add(FAIL, "backend/.env", "不存在，请复制 .env.example 后填写")
        return {}
    env = _load_env(ENV_FILE)
    required = [
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "JWT_SECRET",
        "LLM_BASE_URL",
        "EMBED_BASE_URL",
        "RERANK_BASE_URL",
        "OCR_BASE_URL",
    ]
    missing = [k for k in required if not env.get(k)]
    placeholders = [
        k
        for k in required
        if any(tag in str(env.get(k, "")) for tag in ("你的", "改成", "填你的", "请替换"))
    ]
    if missing:
        add(FAIL, "backend/.env 必填项", "缺少：" + ", ".join(missing))
    elif placeholders:
        add(FAIL, "backend/.env 必填项", "仍是占位值：" + ", ".join(placeholders))
    else:
        add(OK, "backend/.env 必填项", f"已填写 {len(required)} 项")
    secret = env.get("JWT_SECRET", "")
    if secret and len(secret) < 32:
        add(FAIL, "JWT_SECRET", f"长度 {len(secret)}，要求 >=32")
    return env


def check_tcp(host: str, port: int, item: str, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError as exc:
        add(FAIL, item, f"{host}:{port} 连不上（{exc.__class__.__name__}）")
        return False


def check_mysql(env: dict[str, str]) -> None:
    if not env:
        return
    host = env.get("MYSQL_HOST", "127.0.0.1")
    port = int(env.get("MYSQL_PORT", "3306"))
    if check_tcp(host, port, "MySQL"):
        add(OK, "MySQL", f"{host}:{port} 可连接")


def check_http(name: str, url: str, level_if_down: str = WARN) -> None:
    try:
        with urlopen(url, timeout=4) as resp:  # noqa: S310 - 固定内网/自填地址
            add(OK, name, f"{url} -> {resp.status}")
    except (URLError, OSError, ValueError) as exc:
        add(level_if_down, name, f"{url} 不可达（{exc.__class__.__name__}），云端未开机会是这个结果")


def check_model_endpoints(env: dict[str, str]) -> None:
    if not env:
        return
    ocr = env.get("OCR_BASE_URL", "")
    embed = env.get("EMBED_BASE_URL", "")
    if ocr:
        check_http("model-service", ocr.rstrip("/") + "/healthz")
    llm = env.get("LLM_BASE_URL", "")
    if llm:
        check_http("vLLM", llm.rstrip("/") + "/models")
    if embed and embed != ocr:
        check_http("embedding", embed.rstrip("/") + "/healthz")


def check_disk() -> None:
    usage = shutil.disk_usage(ROOT)
    free_gb = usage.free / 1024**3
    add(OK if free_gb >= 10 else WARN, "磁盘余量", f"{free_gb:.1f} GB（建议 >=10GB）")


def check_ports(env: dict[str, str] | None = None) -> None:
    app_port = 8080
    if env and env.get("APP_PORT", "").isdigit():
        app_port = int(env["APP_PORT"])
    for port, label in ((app_port, "后端"), (5173, "前端")):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                add(OK, f"端口 {port}", f"空闲（{label}）")
            except OSError:
                add(WARN, f"端口 {port}", "被占用，启动前先释放")


def check_dirs() -> None:
    for rel in ("data", "data/chroma", "data/uploads", "logs"):
        d = ROOT / rel
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            add(OK, f"目录 {rel}", "可写")
        except OSError as exc:
            add(FAIL, f"目录 {rel}", f"不可写（{exc.__class__.__name__}）")


def check_gpu() -> None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            add(OK, "GPU", out.stdout.strip())
        else:
            add(OK, "GPU", "本机无 GPU（符合预期：模型都在云端）")
    except (FileNotFoundError, subprocess.SubprocessError):
        add(OK, "GPU", "本机无 GPU（符合预期：模型都在云端）")


def check_git() -> None:
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        add(OK, "Git", out)
    except (FileNotFoundError, subprocess.SubprocessError):
        add(FAIL, "Git", "未安装")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    print(f"工作目录：{ROOT}\n")
    check_python()
    check_node()
    env = check_env_file()
    check_mysql(env)
    check_model_endpoints(env)
    check_disk()
    check_ports(env)
    check_dirs()
    check_gpu()
    check_git()

    width = max(len(item) for _, item, _ in results)
    for level, item, detail in results:
        print(f"[{level:^4}] {item.ljust(width)}  {detail}")

    fails = sum(1 for lv, _, _ in results if lv == FAIL)
    warns = sum(1 for lv, _, _ in results if lv == WARN)
    print(f"\n合计 {len(results)} 项：OK {len(results) - fails - warns}，WARN {warns}，FAIL {fails}")
    if fails:
        print("存在 FAIL，先修完再继续（多数是 .env 没填或 MySQL 没起）。")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
