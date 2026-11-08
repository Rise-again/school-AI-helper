# 校园智能助手

面向高校的校园问答与教务服务系统。三角色（访客 / 学生 / 管理员），回答附原文依据，支持知识库管理与教务查询。

> 状态：P0–P2 已完成并在真实 GPU 服务器上验证（上传 → 解析 → 切片 → 向量入库 → 检索命中 0.87）。
> 许可：[MIT](LICENSE)

## 一键安装

### GPU 服务器（Ubuntu 22.04 + NVIDIA，模型跑在这里）

```bash
git clone <你的仓库地址> && cd school_AI_helper
bash install.sh
```

脚本会依次完成：环境检查 → 系统依赖 → 三个独立虚拟环境 → 依赖安装 → 模型权重下载（约 20GB）→ MySQL 建库与建表 → 演示数据 → 自检。

常用参数：

```bash
bash install.sh --skip-models   # 先不下载模型（之后跑 scripts/fetch_models.sh）
bash install.sh --skip-db       # 不动数据库
DATA_ROOT=/opt/campus bash install.sh    # 换数据目录
```

> 默认数据目录是 `/hy-tmp/campus`（恒源云的数据盘）。其它环境请用 `DATA_ROOT` 指到自己的大盘，例如 `DATA_ROOT=/opt/campus`——模型和虚拟环境加起来约 30GB，不要放系统盘。

装完启动：

```bash
bash scripts/start.sh     # vLLM → model-service → 后端，逐个等就绪
curl -s http://127.0.0.1:8080/readyz
```

### Windows 开发机（只装 Web 栈，模型调用云端）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

本机**不安装** torch / paddle / vLLM，也不下载任何模型权重——所有模型通过 HTTP 调云端，安装体量从数 GB 降到百 MB。

## 架构

```
[浏览器] ──HTTPS──> [FastAPI + MySQL + ChromaDB]  ← 前后端同端口
                              │ HTTP
                              ▼
                    [云端 GPU：vLLM + model-service]
                    Qwen2.5-7B / bge-large / bge-reranker / PaddleOCR
```

模型服务是本仓库的一部分（`model_service/`），用 FastAPI 包装选型内的模型，不与后端共用虚拟环境（vLLM 与 bge 对 torch 版本要求不同）。

## 技术栈

Python 3.11 ｜ Vue 3 + Vite + Element Plus ｜ Ubuntu 22.04 LTS ｜ PaddleOCR + MarkItDown ｜ 正方教务 SDK（school-sdk）+ AnySearch API ｜ FastAPI + Uvicorn + Pydantic ｜ MySQL ｜ Qwen2.5-7B-Instruct ｜ Llama-Factory + QLoRA-SFT ｜ vLLM ｜ LangGraph ｜ bge-large-zh-v1.5 + bge-reranker-v2-m3 + ChromaDB

版本锁定与实测组合见 [docs/02-版本矩阵.md](docs/02-版本矩阵.md)（含 6 个踩坑记录，例如 vLLM 0.31 依赖 CUDA 13、驱动 570 带不动）。

## 目录

```
install.sh               一键安装（Linux）
scripts/
  install_windows.ps1    Windows 开发机
  fetch_models.sh        模型权重下载
  start.sh / stop.sh     启停三个服务
  gen_env.py             由 .env.example 生成 backend/.env
  migrate.py             数据库迁移
  seed_demo.py           演示账号
  check_env.py           环境自检
backend/                 FastAPI（api / services / repositories / agents / rag / integrations）
model_service/           模型服务（embeddings / rerank / ocr）
migrations/              SQL 迁移
docs/                    需求、版本、架构、库表、接口、部署、测试、预算
```

## 常用命令

| 命令 | 作用 |
|---|---|
| `bash scripts/start.sh` | 启动全部服务（已在跑的跳过） |
| `bash scripts/stop.sh` | 停止全部服务 |
| `bash scripts/fetch_models.sh` | 补下模型 |
| `bash scripts/backup.sh --full` | 备份到恒源云「个人数据」（需先 `oss login`） |
| `bash scripts/restore.sh --timestamp <时间戳> --full` | 从备份恢复 |
| `python scripts/check_env.py` | 环境自检 |
| `cd backend && pytest` | 后端测试（55 条；加 `TEST_MYSQL=1` 跑 5 条真库用例） |
| `cd model_service && pytest` | 模型服务契约测试（8 条） |

## 配置

复制 `.env.example` 为 `backend/.env`（`install.sh` 会自动生成并填随机密钥），关键项：

| 变量 | 说明 |
|---|---|
| `MYSQL_*` | 数据库连接 |
| `JWT_SECRET` | ≥32 字符，生产必须更换 |
| `LLM_BASE_URL` | vLLM 的 OpenAI 兼容地址 |
| `EMBED_BASE_URL` / `RERANK_BASE_URL` / `OCR_BASE_URL` | model-service 地址 |
| `ANYSEARCH_API_KEY` | 可选；不填则只用静态知识库，不报错 |
| `EDU_HOST` / `EDU_PORT` | 教务系统（默认 zfjw.hntou.edu.cn:80） |

## 演示账号

`admin / Admin@12345`（管理员）、`20230001 / Student@123`（学生）。**上线前必须修改。**

## 文档

[需求基线](docs/01-需求基线.md) ｜ [版本矩阵](docs/02-版本矩阵.md) ｜ [架构](docs/03-架构设计.md) ｜ [库表](docs/04-数据库设计.md) ｜ [API](docs/05-API规范.md) ｜ [部署](docs/06-部署手册.md) ｜ [测试](docs/07-测试计划.md) ｜ [预算](docs/08-资源预算.md) ｜ [部署决策](docs/09-部署决策.md) ｜ [开发日志](docs/devlog.md)
