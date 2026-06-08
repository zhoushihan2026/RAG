import { describe, it, expect, vi, beforeEach } from "vitest";

// mock fetch 全局对象
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

// mock ReadableStream 用于 SSE 测试
function createMockReadableStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]));
        index++;
      } else {
        controller.close();
      }
    },
  });
}

import { sendQuestion, uploadFile, getKBStatus } from "@/api";

describe("sendQuestion", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("请求失败时触发 error 事件", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "服务器错误" }),
    });

    const onEvent = vi.fn();
    await sendQuestion("测试问题", "test-session-id", onEvent);

    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "error" })
    );
  });

  it("成功接收 SSE status 事件", async () => {
    const sseChunk = "event: status\ndata: 正在检索文档...\n\n";
    mockFetch.mockResolvedValue({
      ok: true,
      body: createMockReadableStream([sseChunk]),
    });

    const onEvent = vi.fn();
    await sendQuestion("测试问题", "test-session-id", onEvent);

    expect(onEvent).toHaveBeenCalledWith({
      type: "status",
      content: "正在检索文档...",
    });
  });

  it("成功接收 SSE done 事件", async () => {
    const doneData = JSON.stringify({ final_answer: "答案" });
    const sseChunk = `event: done\ndata: ${doneData}\n\n`;
    mockFetch.mockResolvedValue({
      ok: true,
      body: createMockReadableStream([sseChunk]),
    });

    const onEvent = vi.fn();
    await sendQuestion("测试问题", "test-session-id", onEvent);

    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "done",
        content: expect.objectContaining({ final_answer: "答案" }),
      })
    );
  });

  it("成功接收 SSE error 事件", async () => {
    const sseChunk = 'event: error\ndata: {"error":"出错了"}\n\n';
    mockFetch.mockResolvedValue({
      ok: true,
      body: createMockReadableStream([sseChunk]),
    });

    const onEvent = vi.fn();
    await sendQuestion("测试问题", "test-session-id", onEvent);

    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "error" })
    );
  });

  it("成功接收 SSE stream_start 事件", async () => {
    const sseChunk = "event: stream_start\ndata: \n\n";
    mockFetch.mockResolvedValue({
      ok: true,
      body: createMockReadableStream([sseChunk]),
    });

    const onEvent = vi.fn();
    await sendQuestion("测试问题", "test-session-id", onEvent);

    expect(onEvent).toHaveBeenCalledWith({
      type: "stream_start",
      content: "",
    });
  });

  it("成功接收 SSE token 事件", async () => {
    const sseChunk = "event: token\ndata: 你好\n\n";
    mockFetch.mockResolvedValue({
      ok: true,
      body: createMockReadableStream([sseChunk]),
    });

    const onEvent = vi.fn();
    await sendQuestion("测试问题", "test-session-id", onEvent);

    expect(onEvent).toHaveBeenCalledWith({
      type: "token",
      content: "你好",
    });
  });

  it("body 为空时触发 error 事件", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      body: null,
    });

    const onEvent = vi.fn();
    await sendQuestion("测试问题", "test-session-id", onEvent);

    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "error" })
    );
  });
});

describe("uploadFile", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("上传成功返回响应", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "success",
        message: "上传成功",
        file_name: "test.pdf",
      }),
    });

    const file = new File(["content"], "test.pdf", { type: "application/pdf" });
    const result = await uploadFile(file);

    expect(result.status).toBe("success");
    expect(result.file_name).toBe("test.pdf");
  });

  it("上传失败抛出异常", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "文件格式错误" }),
    });

    const file = new File(["content"], "test.txt", { type: "text/plain" });
    await expect(uploadFile(file)).rejects.toThrow("文件格式错误");
  });
});

describe("getKBStatus", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("获取知识库状态成功", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        total_files: 2,
        files: [
          { sha1: "abc", file_name: "a.pdf", company_name: "公司A" },
          { sha1: "def", file_name: "b.pdf", company_name: "公司B" },
        ],
      }),
    });

    const result = await getKBStatus();
    expect(result.total_files).toBe(2);
    expect(result.files).toHaveLength(2);
  });

  it("获取失败抛出异常", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
    });

    await expect(getKBStatus()).rejects.toThrow("获取知识库状态失败");
  });
});
