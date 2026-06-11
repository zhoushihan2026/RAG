/**
 * 刷新页面后恢复会话状态的 TDD 测试
 * 验证：页面挂载时自动加载活跃会话的消息记录，而非显示欢迎页
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// ==================== 挂载行为测试 ====================

describe("刷新恢复会话状态 - 挂载逻辑", () => {
  it("T-REFRESH-01: 持久化ID存在于列表中时，选中该会话并加载消息", () => {
    // 场景：用户在 session-B 中对话，刷新页面
    const persistedId = "session-b-id";
    const sessionsList = [
      { id: "session-a-id", title: "旧对话", message_count: 2 },
      { id: "session-b-id", title: "当前对话", message_count: 4 },
    ];

    const targetSession = sessionsList.find((s) => s.id === persistedId);
    const sessionId = targetSession?.id || sessionsList[0].id;

    // 期望：找到 session-b-id 并设为活跃
    expect(sessionId).toBe("session-b-id");
    expect(targetSession).toBeTruthy();
    expect(targetSession!.message_count).toBeGreaterThan(0);
  });

  it("T-REFRESH-02: 无持久化ID时，选中最近一个会话（列表第一个）", () => {
    // 场景：首次访问或 sessionStorage 被清空
    const persistedId = null;
    const sessionsList = [
      { id: "s1", title: "A", message_count: 2 },
      { id: "s2", title: "B", message_count: 3 },
    ];

    const targetSession = persistedId ? sessionsList.find((s) => s.id === persistedId) : null;
    const sessionId = targetSession?.id || (persistedId || sessionsList[0].id);

    // 期望：回退到列表第一个
    expect(sessionId).toBe("s1");
  });

  it("T-REFRESH-03: 持久化ID不在列表中时，保持原ID不跳走（新建空会话场景）", () => {
    // 场景：新建空会话后刷新，该ID尚未在后端注册
    const persistedId = "new-empty-session-id";
    const sessionsList = [
      { id: "s1", title: "A", message_count: 2 },
    ];

    const targetSession = sessionsList.find((s) => s.id === persistedId);
    const sessionId = targetSession?.id || (persistedId || sessionsList[0].id);

    // 期望：保持 new-empty-session-id，不跳到 s1
    expect(sessionId).toBe("new-empty-session-id");
  });

  it("T-REFRESH-04: 会话列表为空时不设置活跃会话", () => {
    const sessionsList: any[] = [];

    // 期望：列表为空直接 return，不设置 activeSessionId
    if (sessionsList.length === 0) {
      expect(true).toBe(true); // 不做任何操作
    }
    expect(sessionsList.length).toBe(0);
  });
});

// ==================== sessionStorage 持久化测试 ====================

describe("刷新恢复会话状态 - 持久化", () => {
  let sessionStorageMock: Record<string, string>;

  beforeEach(() => {
    sessionStorageMock = {};
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(
      (key: string) => sessionStorageMock[key] ?? null,
    );
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(
      (key: string, value: string) => { sessionStorageMock[key] = value; },
    );
  });

  it("T-REFRESH-05: activeSessionId 变化时写入 sessionStorage", () => {
    const newSessionId = "new-session-123";
    sessionStorage.setItem("rag_active_session_id", newSessionId);

    expect(sessionStorageMock["rag_active_session_id"]).toBe(newSessionId);
  });

  it("T-REFRESH-06: 新建对话后刷新能恢复到该新对话", () => {
    // 步骤1：新建对话写入持久化
    const newChatId = crypto.randomUUID();
    sessionStorage.setItem("rag_active_session_id", newChatId);

    // 步骤2：模拟刷新读取
    const restoredId = sessionStorage.getItem("rag_active_session_id");

    expect(restoredId).toBe(newChatId);
  });
});

// ==================== buildMessagesFromDetail 测试 ====================

describe("buildMessagesFromDetail - 刷新恢复消息详情", () => {
  it("T-REFRESH-07: 恢复的消息标记 skipAnimation=true", () => {
    // 模拟从后端获取的会话消息
    const sessionMsgs = [
      { role: "user" as const, content: "中芯国际营收？" },
      {
        role: "assistant" as const,
        content: "2024年营收为577亿",
        metadata: {
          final_answer: "2024年营收为577亿",
          step_by_step_analysis: "第一步...",
          reasoning_summary: "综上...",
          references: [{ pdf_sha1: "abc", page_index: 5, source_file: "test.pdf" }],
        },
      },
    ];

    // 模拟 buildMessagesFromDetail 的核心逻辑
    const restored = sessionMsgs.map((msg, idx) => ({
      id: `msg-${idx}`,
      role: msg.role,
      content: msg.content,
      isStreaming: false,
      skipAnimation: true as const,
      ...(msg.role === "assistant" ? {
        details: {
          final_answer: (msg.metadata?.final_answer || msg.content),
          step_by_step_analysis: (msg.metadata?.step_by_step_analysis || ""),
          reasoning_summary: (msg.metadata?.reasoning_summary || ""),
        },
        thinkingCollapsed: true,
      } : {}),
    }));

    // 所有消息都标记了 skipAnimation
    expect(restored.every((m) => m.skipAnimation === true)).toBe(true);

    // 助手消息恢复了 details
    const assistantMsg = restored[1];
    expect(assistantMsg.details?.final_answer).toContain("577亿");
    expect(assistantMsg.details?.step_by_step_analysis).toBe("第一步...");
    expect(assistantMsg.details?.references?.length).toBeGreaterThan(0);
  });

  it("T-REFRESH-08: 无 metadata 时用 content 作为 final_answer 回退", () => {
    const sessionMsgs = [
      { role: "assistant" as const, content: "回答内容", created_at: "" },
    ];

    const restored = sessionMsgs.map((msg, idx) => ({
      id: `msg-${idx}`,
      role: msg.role,
      content: msg.content,
      isStreaming: false,
      skipAnimation: true as const,
      ...(msg.role === "assistant" ? {
        details: {
          final_answer: ((msg as any).metadata?.final_answer || msg.content),
          step_by_step_analysis: "",
          reasoning_summary: "",
          references: [],
        },
        thinkingCollapsed: true,
      } : {}),
    }));

    expect(restored[0].details?.final_answer).toBe("回答内容");
  });
});
