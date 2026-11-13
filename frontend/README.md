# 前端（Vue 3 + Vite + Element Plus）

## 开发

```bash
npm install
npm run dev        # http://127.0.0.1:5173，/api 代理到 127.0.0.1:8080
```

## 构建与部署

```bash
npm run build      # 产物在 dist/
```

生产环境由 FastAPI 托管 `frontend/dist`（单端口 8080），不需要额外 Web 服务器：

- `/assets/*` 由 StaticFiles 直出
- `/` 返回 index.html
- 路由用 **hash 模式**，因为平台自定义服务只映射一个端口、没有静态回退，history 模式刷新会 404

部署时把 `dist/` 同步到服务器 `frontend/dist` 即可，无需在服务器安装 Node。
