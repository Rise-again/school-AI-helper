# 校园智能助手

海南热带海洋学院校园问答与教务服务系统。三角色（访客 / 学生 / 管理员），问答带原文依据，支持知识库管理与教务查询。

> 当前状态：**P0 工程基建**（2026-11-07）。代码尚未开始，先完成需求基线、版本锁定与工程骨架。

## 架构一句话

本地 Windows 只跑 Web 栈（FastAPI + MySQL + ChromaDB 客户端），**所有模型都在云端**：Qwen2.5-7B（vLLM）、bge-large-zh-v1.5、bge-reranker-v2-m3、PaddleOCR 由云端 `model-service` 统一暴露 HTTP 接口。本地通过 `LLMClient / EmbeddingClient / RerankerClient` 三个客户端调用，模型在哪对业务代码不可见。

```
[浏览器] → [Vue3 前端] → [FastAPI 后端 + MySQL + ChromaDB]
                                   │  HTTP（内网/公网）
                                   ▼
                        [云端 GPU: vLLM + model-service]
                        Qwen2.5-7B / bge-large / bge-reranker / PaddleOCR
```

## 技术栈（冻结，不得替换）

Python 3.10 ｜ Vue 3 + Vite + Element Plus ｜ Ubuntu 22.04 LTS ｜ PaddleOCR + MarkItDown ｜ 正方教务 SDK（school-sdk）+ AnySearch API ｜ FastAPI + Uvicorn + Pydantic ｜ MySQL ｜ Qwen2.5-7B-Instruct ｜ Llama-Factory + QLoRA-SFT ｜ vLLM ｜ LangGraph ｜ bge-large-zh-v1.5 + bge-reranker-v2-m3 + ChromaDB

## 目录

```
backend/          FastAPI 服务（api / services / repositories / agents / rag / integrations）
  app/core/       配置、日志、异常、安全
  tests/          单元与集成测试
frontend/         Vue 3 应用（P6 开始搭脚手架）
scripts/          环境检查、迁移、评测、压测、部署
docs/             需求、版本、架构、库表、接口、部署、测试、预算
```

## 快速开始（开发机：Windows 11）

1. **Python 3.10.x**（安装时勾选 Add python.exe to PATH），`python -V` 应为 `3.10.x`
2. **Node 22 LTS**，`node -v` 与 `.nvmrc` 一致
3. **MySQL 8.0** 本地实例，建库：`CREATE DATABASE campus_assistant DEFAULT CHARSET utf8mb4;`
4. 复制配置：`copy backend\.env.example backend\.env`，按注释填值（缺必填项服务会拒绝启动）
5. 装依赖：`pip install -r backend\requirements-windows.txt`
6. 建库与演示数据：
   ```
   python scripts\migrate.py     :: 建库 + 13 张表
   python scripts\seed_demo.py   :: 演示账号 admin / 20230001 / 20230002
   ```
7. 自检：`python scripts\check_env.py`
8. 起服务：
   ```
   uvicorn app.main:create_app --factory --app-dir backend --port 8000 --reload
   ```
   注意必须带 `--factory`：配置在启动时校验，缺项会直接报错并指出变量名。
   接口文档：http://127.0.0.1:8000/docs

> 本机**不安装** torch / paddle / vllm，也不下载任何模型权重。模型全部在云端，本地只需能访问模型服务地址。

## 环境变量（backend/.env）

| 变量 | 说明 |
|---|---|
| `MYSQL_*` | 数据库连接五件套 |
| `JWT_SECRET` | ≥32 字符，生产环境必须更换 |
| `LLM_BASE_URL` / `LLM_MODEL` | vLLM 的 OpenAI 兼容地址与模型名 |
| `EMBED_BASE_URL` / `RERANK_BASE_URL` / `OCR_BASE_URL` | 云端 model-service 的三个端点 |
| `ANYSEARCH_API_KEY` | 搜索 API Key |
| `EDU_HOST` / `EDU_PORT` | 教务系统地址（zfjw.hntou.edu.cn:80） |

完整清单见 `backend/.env.example`。

## 文档索引

| 文档 | 内容 |
|---|---|
| `docs/01-需求基线.md` | 角色、18 条用例、权限矩阵、验收口径 |
| `docs/02-版本矩阵.md` | 三份依赖的版本与锁定规则 |
| `docs/03-架构设计.md` | 分层、模块边界、数据流 |
| `docs/04-数据库设计.md` | 13 张表（P1 填充） |
| `docs/05-API规范.md` | 接口约定与清单 |
| `docs/06-部署手册.md` | 云端部署、发布、回滚 |
| `docs/07-测试计划.md` | 四层测试与质量门禁 |
| `docs/08-资源预算.md` | 云资源与成本上限 |
| `docs/09-部署决策.md` | 节点、域名、TLS |
| `docs/devlog.md` | 每日开发日志 |

## 约定

分支 `feat/T{任务ID}-{简述}`，提交 `feat: ...` 并关联任务 ID，`main` 受保护。详见开发计划第 4 章。
