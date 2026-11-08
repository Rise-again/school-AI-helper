# 开发日志

## 2026-11-07（周五）· P0 第 1 天

**今天做完**
- 计划升到 v1.2：部署改海外（免备案）、开发环境定 Windows 原生、**所有模型上云**、训练卡定 4090、日期顺延至 12/06。
- P0-01 需求基线：6 条 MVP 拆成 18 条用例（访客 5 / 学生 7 / 管理员 4 / 通用 2），每条带判定口径；三角色 × 13 个接口的权限矩阵。
- P0-02 版本矩阵：锁定运行时与三份依赖（本地后端 / 云端后端 / 模型服务）；本地依赖**不含任何模型运行时**。
- P0-03 仓库骨架：monorepo 五目录 + `.gitignore` + `.nvmrc` + README。
- P0-05 配置模块：`backend/app/core/config.py`，Pydantic 校验，缺项/占位值直接拒绝启动；8 条单元测试通过。
- P0-04 环境检查脚本：`scripts/check_env.py`，只依赖标准库，12 项检查跑通（当前 11 OK / 1 FAIL：`.env` 未建）。
- P0-06 文档骨架：架构、库表、API、部署、测试五份；另出 `08-资源预算`、`09-部署决策`。

**结论/发现**
- 学校教务是**新版正方**：`zfjw.hntou.edu.cn/jwglxt`，SDK 用 `school-sdk`，`host` 直接填域名、`port=80`、`ssl=False`。
- 主站能抓到 97 个 `*.hntou.edu.cn` 子域，白名单基础有了。
- vLLM 只支持 Linux，这条决定了"模型必须上云"，而不是可选项。

**风险变化**
- 新增 R14：云端模型服务是单点，关机即全线不可用。已在 `check_env.py` 里做成 WARN 而不是 FAIL，避免误判。
- R9 从"备案超期"改为"境外访问教务可能被风控"，预案改为超时/重试/缓存/降级。

**明天**
- P0-07 把预算表按你的实际报价填实（等厂商页面）。
- P0-08 等你买域名、加解析；证书你加完 TXT 我来验。
- 开始 P1-01 数据库设计。

**需要你的**
1. 域名 + 解析 + 证书 TXT 记录（按 `docs/09` 第 2 节）。
2. 预算上限取 ¥1200 还是 ¥1800。
3. 生产机按小时还是包月。

---

## 2026-11-07（周五）· P1 第 1 天

**今天做完**
- P1-01 数据库设计：13 张表 DDL 落地（`migrations/0001_init.sql`），外键、唯一键、覆盖索引齐备。
- P1-02 迁移器与种子脚本：`scripts/migrate.py`（支持 `--check`，按 schema_version 增量执行，库名做白名单校验）、`scripts/seed_demo.py`（可重复执行，覆盖式写口令）。
- P1-03 数据访问层：`db/pool.py`（aiomysql 连接池 + 显式事务 + ping）、`repositories/users.py`、`repositories/conversations.py`。
- P1-04 基础设施：结构化 JSON 日志 + trace_id 全链路、脱敏函数、错误码体系（9 类）、统一信封、全局异常处理（含 404/405 也走信封）。
- P1-05 鉴权：bcrypt 口令、HS256 双令牌、登录失败计数与锁定、服务层越权二次校验、角色依赖注入。
- P1-06 会话接口：列表/新建/详情/重命名/删除/消息分页，越权一律 404。
- P1-07 测试基线：25 条用例全部通过（配置 8 + 鉴权 9 + 契约 8）；另有 5 条需要真库的集成测试，用 `TEST_MYSQL=1` 才跑。

**实测结果**
- 起服务（无 MySQL）→ `/healthz` 200、`/readyz` 503 并报出 MySQL 不可用、未带令牌访问 `/me` 返回 2001 信封、参数错误返回 4001 信封、`/openapi.json` 正常。
- 日志为单行 JSON，同一请求的 trace_id 贯穿中间件与业务。

**注意**
- 启动命令必须带 `--factory`：`uvicorn app.main:create_app --factory --app-dir backend`，因为配置在启动时校验。
- 本沙箱没有 MySQL，仓储层与登录流程的**真实数据库验证**要在你本机执行：`migrate → seed → TEST_MYSQL=1 pytest`。

**明天**
- P1 收口：在本机跑通迁移与集成测试，确认 13 张表结构与索引。
- 进入 P2：先做 model-service 的最小可跑版本（/v1/embeddings、/v1/rerank、/v1/ocr），再接解析流水线。

**需要你的**
1. 本机 MySQL 起来后跑一遍 `migrate + seed + TEST_MYSQL=1 pytest`，把报错贴给我。
2. 云端 CPU 实例（P2 用，跑 bge/OCR 即可，不必 GPU）。

---

## 2026-11-07（周五）· P2 第 1 天

**今天做完**
- P2-01 解析：`rag/parser.py`。办公格式走 MarkItDown；PDF 按页抽取文本；**空文本分流**（可见字符 < 50 即判文本层缺失 → 云端 OCR），整篇空则整篇 OCR。这是防止"解析成功但内容为空"的唯一防线。
- P2-02 切片：`rag/chunker.py`。标题感知、300–480 token、80 token 重叠、表格与代码块整块保留、超长硬拆。
- P2-03 向量化与入库：`rag/embedding.py`（OpenAI 兼容，批量、维度校验）、`rag/store.py`（Chroma 封装 + 内存替身）、`rag/indexer.py`（解析→切片→向量→写库，按 file_id 先删后写保证幂等）。
- 知识库接口：`POST/GET /kb/files`、详情、切片分页、重建、删除；异步解析用信号量串行，不引入队列。
- 测试：44 通过 / 5 跳过（跳过的是需要真库的集成用例）。新增 14 条切片/解析 + 5 条入库编排。

**踩到并修掉的坑**
- 切片会超出上限 1–2 token：估算函数带 +2 的边界开销，`hard_split` 没预留 → 改为按 `max-2` 分配，并在 emit 时二次校验。
- `heading_path` 取的是片首标题（太笼统）→ 改为取片尾最具体的标题。

**需要说明的一处取舍**
- PDF 默认按页抽取（pypdf），不是整篇 MarkItDown。原因：MarkItDown 转 PDF 会丢页码，而引用必须能指到"第几页"。MarkItDown 仍负责 docx/pptx/xlsx/html。若你要求严格只用 MarkItDown，把 `PARSE_PDF_MODE=markitdown` 即可切回（代价是没有页码）。

**还没做**
- P2-04 检索与重排（需要 embedding/rerank 服务）
- P2-05 前面的管理接口已通，缺"解析进度实时刷新"的前端配合
- P2-06 评测集（需要真实文档）
- `model_service/` 只有契约和依赖，代码未写

**需要你的**
1. 云端 CPU 实例（跑 bge + OCR，不必 GPU），有了我就能把 model-service 写上去并联调。
2. 20 份真实文档（含 5 份扫描件、2 份表格），用来做解析成功率验收。

---

## 2026-11-08（周六）· P2 第 2 天

**今天做完**
- **model_service 代码补齐**：`/v1/embeddings`、`/v1/rerank`、`/v1/ocr`、`/healthz`。模型惰性加载（首次请求才载入，避免和 vLLM 抢冷启动时间）；PDF 用 pypdfium2 逐页栅格化；OCR 结果做了 2.x/3.x 两种返回格式的兼容。8 条契约测试通过。
- **P2-04 检索与重排**：`rag/retriever.py`。向量召回 top20 → 过滤已删/过期 → 重排 → 阈值 → top5。重排服务挂了自动降级为召回分，不阻断问答。
- **P2-07 时效性治理**：`effective_to` 过期文件默认不返回；管理员可 `include_expired=true` 查看。新增 `source_url` 字段（迁移 0002），引用能点回原文。
- **检索调试接口**：`GET /api/v1/rag/search`（仅管理员），可直接看召回结果与分数，用于调阈值和跑评测。
- 测试：后端 54 通过 / 5 跳过；模型服务 8 通过。

**顺手补的**
- 向量库抽象加了 `query()`（Chroma 用 `1 - cosine distance`，内存实现用点积），三处实现同步。

**还没验的（都需要服务器）**
- 真 bge 的维度与归一化、真 Chroma 的写入与召回、模型服务的显存占用
- P1 的 5 条集成测试（真 MySQL）
- 备份镜像与自定义服务链接

**我这边等的东西**
1. SSH 地址 / 端口 / 密钥路径
2. 20 份真实文档（P2-06 评测集 + 解析成功率验收）

---

## 2026-11-08（周六）· 服务器联调（P0–P2 收口）

**实例实测**
- Ubuntu **22.04.5**（不是 20.04，D-07 撤销，与选题 PPT 一致）、RTX 4090 **24GB**（24564 MiB）、驱动 570.211.01、CUDA 12.8、Python 3.11.12、/hy-tmp 100G。

**跑通了什么**
- MySQL 8.0.46 装好并启动；`migrate` 建 13 张表；`seed` 写入 3 个演示账号；**5 条集成测试全过**（P1 收口）。
- vLLM 0.11.0 服务 7B：显存占 17.2G，一次问答 0.9 秒。
- model-service：embedding 1024 维、rerank 正常（作弊题 0.825）、OCR 已装（CPU 通道）。
- 后端 8080：`/readyz` 三项（mysql / llm / models）全 ok。
- **端到端**：上传《学籍管理规定》→ 解析 → 切片 3 段 → 向量入库 → 检索"考试作弊怎么处理" 命中 0.872，带章节与原文链接。

**踩坑与修正**
1. `python3 -m venv` 缺 ensurepip → 全面改用 virtualenv。
2. MySQL 8 caching_sha2 认证缺 `cryptography` → 补进两份 requirements。
3. `aiomysql` 0.3.x 不再导出 `constants` → `migrate.py` 改从 `pymysql.constants` 取。
4. vLLM 0.31 拉 torch 2.13+cu130，驱动 570 带不动（`cuda_available=False`）→ 降到 0.11.0（torch 2.8+cu128）。
5. vLLM 0.11 与 transformers 5.x 冲突（Qwen2Tokenizer 报错）→ 钉 4.57.1。
6. FlagEmbedding 1.4.2 `encode()` 不认 `normalize_embeddings` → 自己 L2 归一化。
7. **切片不按标题切**：整篇 3 章并成 1 片，重排只有 0.12 分被阈值挡掉 → 改为"标题是硬边界、且不带重叠"，重排升到 0.872。这是今天最有价值的一次修正。

**还没做**
- P2-06 评测集（需要 20 份真实文档）
- P0-08 备份镜像（依赖装完了，可以在控制台创建）、自定义服务链接（需你在控制台点开）
- 数据备份脚本、systemd 托管（属 P9，但建议早做）

---

## 2026-11-08（周六）· 打包与开源准备

**做了什么**
- `install.sh`：七步一键安装（环境检查 → 系统依赖 → 三个虚拟环境 → 依赖 → 模型 → 数据库 → 自检），幂等、可重复执行、支持 `--skip-models/--skip-apt/--skip-db` 和数据目录自定义。
- `scripts/start.sh` / `stop.sh`：按 vLLM → model-service → 后端 的顺序启动，逐个等就绪，pid 落在 `run/`，`stop.sh` 按 pid 停止。
- `scripts/fetch_models.sh`：从 ModelScope 拉 Qwen2.5-7B + 两个 bge，已存在则跳过。
- `scripts/gen_env.py`：由 `.env.example` 生成 `backend/.env`，自动填 32 位 JWT 与数据库口令。
- `scripts/install_windows.ps1`：Windows 开发机只装 Web 栈，模型调用云端。
- 开源配套：MIT LICENSE、`.gitattributes`（强制 sh 用 LF）、GitHub Actions（后端 55 条 + 模型服务 8 条）。

**验证**
- 在服务器上实跑 `bash install.sh --skip-models --skip-db`：识别到三个环境已存在，全部跳过，自检 7 项全绿。
- `bash scripts/start.sh`：vLLM 就绪 → model-service 就绪 → 后端就绪，三个 pid 文件齐全，`/readyz` 三项 ok。

**两个坑**
- `pkill -f "venvs/web/bin/uvicorn"` 会把执行这条命令的 SSH 会话一起杀掉（命令行里含同样字符串），要用 `venvs/[w]eb/...` 的括号写法避开自匹配。
- 在 SSH 非交互会话里用 `nohup ... &` 起长任务，会话结束会被带走；必须 `setsid`。

**公网联调（2026-11-08）**
- 自定义服务实测：`http://i-2.gpushare.com:44368/` → 内网 8080，`/healthz` 200、`/readyz` 三项全绿，`X-Trace-Id` 正常透传。
- **实际是 HTTP 不是 HTTPS**（早期判断有误），令牌在公网明文传输，演示可接受但验收文档要注明。
- 代理响应头 `Keep-Alive: timeout=4`：空闲 4 秒可能断连。**P3 做 SSE 时必须每 2–3 秒发心跳**，否则模型思考超过 4 秒会掐断流。
- 20MB 上传实测：20,971,719 字节全额到达，用时 10.4 秒（约 2MB/s），类型校验正常返回 422/4001。上传体积不是瓶颈。

**备份打通（2026-11-08）**
- 首次全量备份完成：`oss://campus/` 下 5 个文件，共 5.8GB（venv 5.78G + 代码/上传 403K + 库 4.3K + manifest）。
- 校验：从远端拉回库备份，`gunzip` 后 13 张 `CREATE TABLE` 齐全；manifest 字段正确。
- 存储成本约 ¥1.7/月（5.8G × 0.0004 元/GB/时）。
- 踩到的 5 个平台限制，全部修进脚本：
  1. 恒源云 oss **没有 bucket 名**，`oss://` 就是个人数据根；
  2. **只接受压缩包**，不支持文件/目录直传，所以模型也要打包；
  3. **扩展名白名单**里没有 `.tgz` 和 `.txt` → 统一改 `.tar.gz`、manifest 先 gzip；
  4. `oss rm` 默认交互式确认，脚本里必须 `-f`；
  5. `mysqldump` 必须走 `-h127.0.0.1`（授权是 campus@127.0.0.1）并加 `--no-tablespaces`，否则静默产出 20 字节空包。

**P2-05 / P2-07 / P0-04 收口（2026-11-08）**
- P2-05 切片明细与删除接口实测通过：切片返回 ordinal/token 数/heading_path；删除后详情与切片均 404。
- P2-07 时效过滤实测通过：过期文档（effective_to=2024-12-31）默认检索 0 条，`include_expired=true` 返回 1 条且 `expired=true`（0.965 分）。
- P0-04 自检脚本在服务器实跑：15 项，13 OK / 2 WARN / 0 FAIL。
- **修掉两个真 bug**：
  1. 短文本（<50 可见字符）被误判为"文本层缺失"送去 OCR，而 OCR 只认 PDF/图片 → 索引失败。改为只有 PDF/图片走 OCR；顺带补上了图片上传通道（学生拍通知照片的场景）。
  2. `check_env.py` 把 Node 不达标判成 FAIL，但 Node 只用于前端构建、后端运行不需要；Python 3.10 的硬判断也与实际的 3.11 冲突。
