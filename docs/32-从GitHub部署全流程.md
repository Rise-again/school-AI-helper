# 从 GitHub 部署全流程

> 2026-11-15。目标：一台新的 Ubuntu 22.04 + NVIDIA GPU 服务器，从仓库到公网可用。
> 前置：仓库已推送（含 `frontend/dist`、`data/kb_seed`）、HF adapter 已上传。

## 0. 项目作者分享前（只做一次）

本地仓库必须包含前端产物和知识库种子，否则别人 clone 下来没有页面/知识库：

```bash
cd D:\Programs\school_AI_helper
git status --short          # 确认 frontend/dist、data/kb_seed、docs/32 都在
git add -A
git commit -m "P7/P8/P9: 交付版本"
git tag -a v1.0.0 -m "课程交付 v1.0.0"
git push origin main --tags
```

> `frontend/dist` 和 `data/kb_seed` 已通过 `.gitignore` 例外允许入库；如果 `git status` 里没有它们，先检查 `.gitignore` 的两条 `!` 例外。
> adapter 不在 Git 里（161MB），已在 `Rise-again/campus-lora-p4-v1`，别人用本流程的 `ADAPTER_REPO` 拉取。

## 0. 服务器要求

| 项 | 要求 |
|---|---|
| GPU | NVIDIA 24GB（RTX 4090 / 同档），驱动能装 vLLM 0.11（项目实测驱动 570 / CUDA 12.8） |
| 系统 | Ubuntu 22.04.5，root 权限 |
| 内存/CPU | 16 核 / 62GB 内存以上 |
| 磁盘 | 数据盘 `/hy-tmp` ≥50GB（模型+venv 约 35GB） |
| 网络 | 能访问 ModelScope、PyPI、`hf-mirror.com`（HF 上传不需要在服务器做） |
| 端口 | 后端监听 `0.0.0.0:8080`；平台自定义服务映射到公网 |

## 1. 拉代码

```bash
git clone <你的仓库地址> school_AI_helper
cd school_AI_helper
```

确认这两个目录存在（部署必需，已在仓库里）：

```bash
ls frontend/dist/index.html
ls data/kb_seed/manifest.json
```

## 2. 一键安装（含 adapter）

```bash
ADAPTER_REPO=Rise-again/campus-lora-p4-v1 \
ADAPTER_REVISION=73d6f6f5310fee0ccb4aec00d39a6a13884109a9 \
HF_ENDPOINT=https://hf-mirror.com \
bash install.sh
```

脚本会依次做：

1. 检查 GPU/Python/数据盘；
2. 装系统依赖（MySQL、build-essential、virtualenv）；
3. 建 `venvs/web|vllm|models|dl`；
4. 装 Python 依赖（vLLM 0.11、torch 2.9.1、FlagEmbedding、PaddleOCR 等）；
5. 从 ModelScope 下载 Qwen2.5-7B、bge-large、bge-reranker（约 20GB，首次 20–40 分钟）；
6. 建 MySQL 库/用户、生成 `backend/.env`、执行迁移、写演示账号；
7. 从 HF 下载 adapter 到 `data/sft/output`，把 `.env` 的 `LLM_MODEL` 改为 `campus-lora`。

> 没有 HF adapter 时去掉 `ADAPTER_REPO`/`ADAPTER_REVISION`，之后手动 `scripts/fetch_adapter.py`；也可直接把 adapter 放到 `/hy-tmp/campus/data/sft/output`。

> 如果 MySQL root 有密码，`install.sh` 的 `mysql -uroot` 需要改成 `mysql -uroot -p`；或先手工建库/用户后跑 `install.sh --skip-db`。

## 3. 启动

```bash
bash scripts/start.sh
```

它会按 vLLM → model-service → 后端 顺序启动并等就绪（vLLM 首次 1–3 分钟）。检查：

```bash
curl -s http://127.0.0.1:8080/readyz
curl -s http://127.0.0.1:8001/v1/models
```

`/readyz` 四项 `mysql/llm/models/chroma` 全 ok；`/v1/models` 同时有 `qwen2.5-7b-instruct` 和 `campus-lora`。

## 4. 导入知识库（全新库必做）

```bash
/hy-tmp/campus/venvs/web/bin/python scripts/seed_kb.py
```

导入 `data/kb_seed` 的 20 份原始文档，等待解析完成并回填 topics。输出 `DONE` 后检查：

```bash
curl -s http://127.0.0.1:8080/readyz   # chroma 计数应 >0
```

## 5. 生成三角色演示会话

```bash
/hy-tmp/campus/venvs/web/bin/python scripts/seed_demo_chats.py
```

会用 admin/20230001/20230002 各生成 3 个真实问答会话。

## 6. 公网访问

平台控制台把内网 **8080** 映射为自定义服务（本项目实测公网 `http://i-2.gpushare.com:44368/`，HTTP 无 TLS）。打开：

- `/` 首页 → 访客咨询；
- `/login` 登录；
- 管理员 → 知识库管理。

不再需要 Nginx，前端 `dist` 由 FastAPI 托管，前后端同端口。

## 7. 验收自检

```bash
# 探针
curl -s http://127.0.0.1:8080/readyz
# 访客问答（SSE 应逐块）
curl -s -N -X POST http://127.0.0.1:8080/api/v1/chat/anonymous \
  -H 'Content-Type: application/json' -d '{"content":"勤工助学的报酬标准是什么？"}' | head -20
# 巡检
/hy-tmp/campus/venvs/web/bin/python scripts/p9_healthcheck.py
```

演示账号：

| 账号 | 密码 | 角色 |
|---|---|---|
| `admin` | `Admin@12345` | 管理员 |
| `20230001` | `Student@123` | 学生 |
| `20230002` | `Student@123` | 学生 |

## 8. 日常运维

```bash
bash scripts/start.sh                 # 启动全部（重启实例后必须手动执行）
bash scripts/stop.sh                  # 停止
bash scripts/backup.sh --full         # 备份到 OSS（先 oss login）
python scripts/p9_healthcheck.py      # 每日巡检
```

- 容器无 systemd，崩溃不会自动拉起；重启实例后手动 `start.sh`（D-27）。
- `/hy-tmp` 关机 24 小时会清空；每天备份 OSS + 重要节点保存本地完整包。
- 显存/GPU 以容器内 `nvidia-smi` 为准，平台监控页不可信（D-26）。
- 首次上传扫描件时 PaddleOCR 会下载约 171MB 模型到 `/root/.paddlex`；离线部署需预先拷贝。

## 9. 常见问题

| 现象 | 处理 |
|---|---|
| `hf`/`huggingface-cli` 找不到 | 不用 CLI，用 `scripts/fetch_adapter.py`（Python API） |
| 服务器连不上 huggingface.co | 下载加 `--endpoint https://hf-mirror.com`；镜像只读，上传在本地做 |
| vLLM 启动报驱动/CUDA | 对照 `docs/02-版本矩阵`，vLLM 0.11 + 驱动 570 |
| `/readyz` llm down | 看 `/hy-tmp/campus/logs/vllm.log`；显存不足按四级降级（关 eager→重排 CPU→OCR CPU→max-model-len 4096） |
| 没有前端/页面 404 | 确认仓库含 `frontend/dist`（服务器 Node 14 不能构建 Vite 8） |
| MySQL root 连不上 | 用 socket `env -u MYSQL_HOST -u MYSQL_USER -u MYSQL_PASSWORD mysql -uroot` |
| 知识库为空 | 跑 `scripts/seed_kb.py`；全新库迁移不会自动导入文档 |
| 回答像基座、不守约束 | 确认 `.env` `LLM_MODEL=campus-lora` 且 `data/sft/output` 有 adapter，重启后端 |
| 20MB 上传很慢 | 平台代理带宽限制（实测约 127KB/s），演示提前入库 |
