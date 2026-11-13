import type { Citation, StreamEvent, StreamMeta } from "@/types";

/**
 * 流式对话。用 fetch 而不是 axios：需要逐块读取 ReadableStream。
 * 返回一个可中断的控制器，调用 abort() 可停止生成（服务端会把已生成内容落库）。
 */
export function streamChat(
  path: string,
  body: unknown,
  handlers: {
    onMeta?: (m: StreamMeta) => void;
    onDelta?: (text: string) => void;
    onCitations?: (items: Citation[]) => void;
    onDone?: (info: { latency_ms: number; chars: number }) => void;
    onError?: (message: string) => void;
  },
  options: { token?: string } = {},
): { abort: () => void } {
  const controller = new AbortController();

  (async () => {
    try {
      const resp = await fetch(`/api/v1${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!resp.ok || !resp.body) {
        const text = await resp.text().catch(() => "");
        let message = `请求失败（${resp.status}）`;
        try {
          message = JSON.parse(text).message || message;
        } catch {
          /* 保持默认 */
        }
        handlers.onError?.(message);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let eventName = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const raw of lines) {
          const line = raw.replace(/\r$/, "");
          if (!line || line.startsWith(":")) continue; // 心跳
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const payload = line.slice(5).trim();
            if (!payload) continue;
            dispatch(eventName, payload, handlers);
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        handlers.onError?.("网络中断，请重试");
      }
    }
  })();

  return { abort: () => controller.abort() };
}

function dispatch(
  name: string,
  payload: string,
  handlers: Parameters<typeof streamChat>[2],
) {
  let data: unknown;
  try {
    data = JSON.parse(payload);
  } catch {
    return;
  }
  const event = { type: name, data } as StreamEvent;
  switch (event.type) {
    case "meta":
      handlers.onMeta?.(event.data);
      break;
    case "delta":
      handlers.onDelta?.(event.data.text);
      break;
    case "citation":
      handlers.onCitations?.(event.data.items);
      break;
    case "done":
      handlers.onDone?.(event.data);
      break;
    case "error":
      handlers.onError?.(event.data.message);
      break;
  }
}
