/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端地址前缀；留空表示同源 */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
