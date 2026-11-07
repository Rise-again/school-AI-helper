# 云端模型服务

用 FastAPI 包装四类模型，只在内网暴露。

| 端点 | 模型 | 用途 |
|---|---|---|
| `POST /v1/embeddings` | bge-large-zh-v1.5 | 切片与查询向量化（1024 维） |
| `POST /v1/rerank` | bge-reranker-v2-m3 | 候选重排（输入 query + passages） |
| `POST /v1/ocr` | PaddleOCR | 扫描件文字提取，返回文本块与坐标 |
| `GET /healthz` | — | 三个模型是否已加载 |

大模型走独立的 vLLM 进程（`:8001`，OpenAI 兼容），与本服务分 venv。
