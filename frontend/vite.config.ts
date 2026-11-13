import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 开发期把 /api 代理到本机后端；生产由 FastAPI 同源托管（单端口）
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          // rolldown 只接受函数形式
          if (id.includes("node_modules/element-plus")) return "element";
          if (id.includes("node_modules")) return "vendor";
          return undefined;
        },
      },
    },
  },
});
