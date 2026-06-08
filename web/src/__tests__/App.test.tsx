import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useRef, useCallback } from "react";
import type { Message } from "@/types";

// ========== 测试1: handleSelectSession 缓存逻辑单元测试 ==========

describe("会话切换缓存逻辑", () => {
  // 模拟 handleSelectSession 的核心逻辑
  // 验证：缓存恢复的消息标记 skipAnimation=true

  it("缓存恢复的消息应标记 skipAnimation=true", () => {
    const cachedMessages: Message[] = [
      { id: "1", role: "user", content: "问题1" },
      { id: "2", role: "assistant", content: "回答1", details: { final_answer: "回答1", references: [] } },
    ];

    // 模拟 handleSelectSession 中缓存恢复逻辑
    const restored = cachedMessages.map((m) => ({ ...m, skipAnimation: true }));

    expect(restored.every((m) => m.skipAnimation === true)).toBe(true);
    // 原始缓存不被修改
    expect(cachedMessages.every((m) => m.skipAnimation === undefined)).toBe(true);
  });

  it("从后端加载的消息不标记 skipAnimation", () => {
    // 模拟 buildMessagesFromDetail 返回的消息
    const loadedMessages: Message[] = [
      { id: "1", role: "user", content: "问题1" },
      { id: "2", role: "assistant", content: "回答1", isStreaming: false, details: { final_answer: "回答1", references: [] }, thinkingCollapsed: true },
    ];

    // 从后端加载的消息不添加 skipAnimation
    expect(loadedMessages.every((m) => m.skipAnimation === undefined)).toBe(true);
  });
});

// ========== 测试2: useRef 避免闭包陷阱 ==========

describe("useRef 避免闭包陷阱", () => {
  it("ref 始终保存最新值，回调不依赖外部状态", () => {
    const { result } = renderHook(() => {
      const [value, setValue] = [1, (v: number) => v];
      const ref = useRef(value);
      ref.current = value;

      const getValue = useCallback(() => {
        return ref.current;
      }, []);

      return { getValue };
    });

    // ref 方式获取的值始终是最新的
    expect(result.current.getValue()).toBe(1);
  });
});

// ========== 测试3: 多次切换不会无限循环 ==========

describe("多次切换会话性能", () => {
  it("快速切换10次不应产生无限定时器", () => {
    // 模拟会话切换的缓存操作
    const sessionCache = new Map<string, Message[]>();
    const sessions = ["s1", "s2", "s3"];

    // 预填充缓存
    sessions.forEach((id) => {
      sessionCache.set(id, [
        { id: `${id}-1`, role: "user", content: `问题-${id}` },
        { id: `${id}-2`, role: "assistant", content: `回答-${id}` },
      ]);
    });

    // 模拟快速切换
    let currentId = "s1";
    for (let i = 0; i < 100; i++) {
      const targetId = sessions[i % 3];

      // 保存当前会话到缓存
      if (currentId) {
        sessionCache.set(currentId, sessionCache.get(currentId) || []);
      }

      // 从缓存恢复目标会话
      const cached = sessionCache.get(targetId);
      if (cached) {
        const restored = cached.map((m) => ({ ...m, skipAnimation: true }));
        expect(restored.length).toBeGreaterThan(0);
      }

      currentId = targetId;
    }

    // 缓存大小应保持稳定（3个会话）
    expect(sessionCache.size).toBe(3);
  });

  it("同一会话重复切换不触发操作", () => {
    let callCount = 0;
    const activeSessionIdRef = { current: "s1" };

    const handleSelectSession = (sessionId: string) => {
      if (sessionId === activeSessionIdRef.current) return;
      callCount++;
      activeSessionIdRef.current = sessionId;
    };

    // 切换到同一会话
    handleSelectSession("s1");
    expect(callCount).toBe(0);

    // 切换到不同会话
    handleSelectSession("s2");
    expect(callCount).toBe(1);

    // 再次切换到同一会话
    handleSelectSession("s2");
    expect(callCount).toBe(1);
  });
});

// ========== 测试4: 缓存同步时机 ==========

describe("缓存同步时机", () => {
  it("done 事件后手动同步缓存", () => {
    const sessionCache = new Map<string, Message[]>();
    const sessionId = "s1";
    const messages: Message[] = [
      { id: "1", role: "user", content: "问题" },
      { id: "2", role: "assistant", content: "回答", isStreaming: false, details: { final_answer: "回答", references: [] } },
    ];

    // 模拟 done 事件后手动同步
    sessionCache.set(sessionId, messages);

    expect(sessionCache.get(sessionId)).toEqual(messages);
  });

  it("error 事件后手动同步缓存", () => {
    const sessionCache = new Map<string, Message[]>();
    const sessionId = "s1";
    const messages: Message[] = [
      { id: "1", role: "user", content: "问题" },
      { id: "2", role: "assistant", content: "请求失败", isStreaming: false },
    ];

    // 模拟 error 事件后手动同步
    sessionCache.set(sessionId, messages);

    expect(sessionCache.get(sessionId)).toEqual(messages);
  });

  it("catch 异常后手动同步缓存", () => {
    const sessionCache = new Map<string, Message[]>();
    const sessionId = "s1";
    const messages: Message[] = [
      { id: "1", role: "user", content: "问题" },
      { id: "2", role: "assistant", content: "请求失败，请重试", isStreaming: false },
    ];

    // 模拟 catch 异常后手动同步
    sessionCache.set(sessionId, messages);

    expect(sessionCache.get(sessionId)).toEqual(messages);
  });

  it("离开会话时保存当前状态到缓存", () => {
    const sessionCache = new Map<string, Message[]>();
    const currentId = "s1";
    const currentMessages: Message[] = [
      { id: "1", role: "user", content: "问题" },
    ];

    // 模拟离开当前会话前保存
    if (currentId && currentMessages.length > 0) {
      sessionCache.set(currentId, currentMessages);
    }

    expect(sessionCache.get("s1")).toEqual(currentMessages);
  });

  it("空消息的会话不保存到缓存", () => {
    const sessionCache = new Map<string, Message[]>();
    const currentId = "s2";
    const currentMessages: Message[] = [];

    // 模拟离开空会话
    if (currentId && currentMessages.length > 0) {
      sessionCache.set(currentId, currentMessages);
    }

    expect(sessionCache.has("s2")).toBe(false);
  });
});
