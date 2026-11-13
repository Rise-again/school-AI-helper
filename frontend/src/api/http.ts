import axios from "axios";
import { ElMessage } from "element-plus";
import type { Envelope } from "@/types";

const http = axios.create({
  baseURL: "/api/v1",
  timeout: 20000,
});

/** token 与刷新：401 时自动换一次，失败则回登录页 */
let refreshing: Promise<string | null> | null = null;

function getAccess(): string {
  return localStorage.getItem("access_token") || "";
}

function setTokens(access: string, refresh: string) {
  localStorage.setItem("access_token", access);
  localStorage.setItem("refresh_token", refresh);
}

export function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("profile");
}

http.interceptors.request.use((config) => {
  const token = getAccess();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

http.interceptors.response.use(
  (resp) => {
    const body = resp.data as Envelope<unknown>;
    if (body && typeof body.code === "number" && body.code !== 0) {
      ElMessage.error(body.message || "请求失败");
      return Promise.reject(new Error(body.message));
    }
    return resp;
  },
  async (error) => {
    const resp = error.response;
    const status = resp?.status;
    const code = resp?.data?.code;

    if (status === 401 && code === 2001) {
      const refreshToken = localStorage.getItem("refresh_token");
      if (refreshToken && !error.config.__retried) {
        refreshing ??= axios
          .post<Envelope<{ access_token: string; refresh_token: string }>>(
            "/api/v1/auth/refresh",
            { refresh_token: refreshToken },
          )
          .then((r) => {
            const data = r.data.data;
            setTokens(data.access_token, data.refresh_token);
            return data.access_token;
          })
          .catch(() => null)
          .finally(() => {
            refreshing = null;
          });

        const token = await refreshing;
        if (token) {
          error.config.__retried = true;
          error.config.headers.Authorization = `Bearer ${token}`;
          return http.request(error.config);
        }
      }
      clearTokens();
      if (location.hash !== "#/login") location.hash = "#/login";
      ElMessage.warning("登录已过期，请重新登录");
      return Promise.reject(error);
    }

    const message = resp?.data?.message || (status ? `请求失败（${status}）` : "网络异常");
    ElMessage.error(message);
    return Promise.reject(error);
  },
);

export default http;
export { setTokens };
