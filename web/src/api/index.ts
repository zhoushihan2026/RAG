import type { SSEEvent, UploadResponse, KBStatus } from "@/types";

const API_BASE = "/api";

// 发送问答请求，返回 SSE 事件流
export async function sendQuestion(
  question: string,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "请求失败" }));
    onEvent({ type: "error", content: error.detail || "请求失败" });
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    onEvent({ type: "error", content: "浏览器不支持流式读取" });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // 按双换行分割 SSE 事件块
    const parts = buffer.split("\n\n");
    // 最后一段可能不完整，保留在 buffer 中
    buffer = parts.pop() || "";

    for (const part of parts) {
      if (!part.trim()) continue;

      let currentEventType = "";
      let currentData = "";

      for (const line of part.split("\n")) {
        if (line.startsWith("event: ")) {
          currentEventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          currentData = line.slice(6);
        }
      }

      if (!currentEventType) continue;

      // 解析事件内容
      if (currentEventType === "done") {
        // done 事件的 data 是 JSON 对象
        try {
          const parsed = JSON.parse(currentData);
          onEvent({ type: "done", content: parsed });
        } catch {
          onEvent({ type: "done", content: {} });
        }
      } else if (currentEventType === "error") {
        // error 事件的 data 可能是 JSON 或纯文本
        try {
          const parsed = JSON.parse(currentData);
          onEvent({ type: "error", content: parsed.error || currentData });
        } catch {
          onEvent({ type: "error", content: currentData });
        }
      } else if (currentEventType === "token") {
        // token 事件的 data 是纯文本
        onEvent({ type: "token", content: currentData });
      } else if (currentEventType === "stream_start") {
        // stream_start 事件无实质内容
        onEvent({ type: "stream_start", content: "" });
      } else if (currentEventType === "status") {
        // status 事件的 data 是纯文本
        onEvent({ type: "status", content: currentData });
      } else {
        // 未知事件类型
        onEvent({ type: currentEventType as SSEEvent["type"], content: currentData });
      }
    }
  }
}

// 上传 PDF 文件
export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "上传失败" }));
    throw new Error(error.detail || "上传失败");
  }

  return response.json();
}

// 获取知识库状态
export async function getKBStatus(): Promise<KBStatus> {
  const response = await fetch(`${API_BASE}/kb/status`);

  if (!response.ok) {
    throw new Error("获取知识库状态失败");
  }

  return response.json();
}
