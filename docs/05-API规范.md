# API 规范

## 1. 基本约定

前缀 `/api/v1`；`Authorization: Bearer <JWT>`；请求体与响应体一律 JSON（上传除外）；时间用 ISO 8601（`2026-11-07T10:00:00+08:00`）。

统一响应：

```json
{ "code": 0, "message": "ok", "data": {}, "trace_id": "a1b2c3d4" }
```

`code` 为 0 表示成功，非 0 为业务错误码；HTTP 状态码同时表达语义（400/401/403/404/422/429/500）。

## 2. 错误码

| code | HTTP | 含义 | 前端处理 |
|---|---|---|---|
| 0 | 200 | 成功 | — |
| 1001 | 400 | 参数错误 | 提示具体字段 |
| 2001 | 401 | 未登录/令牌过期 | 跳登录，自动刷新一次 |
| 2002 | 403 | 越权 | 提示无权限 |
| 3001 | 404 | 资源不存在 | 提示并返回列表 |
| 4001 | 422 | 业务校验失败 | 展示 message |
| 5001 | 429 | 限流 | 提示"稍后再试"+ 建议排队 |
| 6001 | 503 | 依赖不可用（模型/教务/搜索） | 降级文案 + 重试按钮 |
| 9001 | 500 | 未预期错误 | 提示 + trace_id |

## 3. 分页

`?page=1&size=20`，响应 `data: {items: [], total: 0, page: 1, size: 20}`；size 上限 100。

## 4. 流式对话（SSE）

`POST /conversations/{id}/messages` 返回 `text/event-stream`，事件类型：

| event | data | 说明 |
|---|---|---|
| `meta` | `{intent, evidence_count, degraded, prompt_version}` | 开始，告知意图、证据条数与降级原因 |
| `delta` | `{text}` | 增量文本，可多次 |
| `replace` | `{text}` | 落地校验后**整段替换**已输出内容；前端收到后直接覆盖，不追加 |
| `citation` | `{items: [{kb_file_id, chunk_id, page_no, url, snippet, score}]}` | 引用块，结束前一次性下发，只含回答里真正引用到的条目 |
| `done` | `{latency_ms, chars}` | 结束，消息已落库 |
| `error` | `{message}` | 出错，前端展示重试 |

流式期间每 2.5 秒发一行 `: ping` 注释（平台代理空闲 4 秒即断流）。`replace` 可能不出现在某条回答里：只有在回答含资料中没有的具体内容、被落地校验改写时才会发出。

客户端断开时必须保证消息完整落库（服务端在 `finally` 中补写）。

## 5. 接口清单

见开发计划附录 A；P1 起每个接口补请求/响应示例与错误分支，并在 `/docs` 中核对 OpenAPI 契约。

### 5.1 教务接口（P5）

仅学生角色，仅本人数据；口令用 AES-GCM 密文存 `student_profile.edu_cred_cipher`，服务端不保存明文。会话为进程内缓存，失效后自动重登一次。

| 方法 | 路径 | 请求 | 响应 `data` |
|---|---|---|---|
| GET | `/edu/status` | — | `{bound, student_no, updated_at}`；不访问教务 |
| POST | `/edu/bind` | `{student_no, password}` | 同 status；先登录验证再落库 |
| DELETE | `/edu/bind` | — | `null` |
| GET | `/edu/schedule` | — | `{items: [{weekday, sections, course, teacher, location, weeks}]}`，本学期 |
| GET | `/edu/grades` | `?term=2025-2026-2`（可选） | `{terms: [], items: [{course, credit, score, gpa, term}]}` |
| GET | `/edu/credits` | — | `{required, earned, gpa, categories: [{name, required, earned}]}` |

错误分支：未绑定 → 400/1001（"尚未绑定教务账号"）；教务账号密码错 → 400/1001；教务不可达（校园网限制、系统故障、超时）→ 503/6001，message 为"教务系统暂时无法访问"，前端提示稍后重试；管理员 → 403/2002。

对话中的"我的课表/成绩/学分"由 `edu` 意图节点直接查上述数据并以模板作答，不经过大模型，因此不会编造；教务不可达时回复同样的降级话术。

## 6. 版本策略

破坏性变更升 `/api/v2`，旧版保留一个迭代。非破坏性变更（新增字段）直接在当前版本加，前端必须容忍未知字段。
