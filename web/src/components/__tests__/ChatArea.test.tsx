import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { ChatArea } from "@/components/ChatArea";
import type { Message } from "@/types";

// mock scrollIntoView（jsdom 不支持）
Element.prototype.scrollIntoView = vi.fn();

// 制造消息的辅助函数
function makeMessage(overrides: Partial<Message> & { id: string; role: "user" | "assistant" }): Message {
  return {
    content: "",
    ...overrides,
  };
}

describe("ChatArea", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("空消息列表时不渲染任何消息", () => {
    const { container } = render(<ChatArea messages={[]} />);
    expect(container.querySelector(".flex.justify-end")).toBeNull();
    expect(container.querySelector(".flex.justify-start")).toBeNull();
  });

  it("渲染用户消息", () => {
    const messages: Message[] = [
      makeMessage({ id: "1", role: "user", content: "你好" }),
    ];
    render(<ChatArea messages={messages} />);
    expect(screen.getByText("你好")).toBeInTheDocument();
  });

  it("渲染助手消息（已完成，有 details）", () => {
    const messages: Message[] = [
      makeMessage({
        id: "2",
        role: "assistant",
        content: "这是回答内容，足够长以避免被判定为错误消息",
        isStreaming: false,
        details: {
          final_answer: "这是回答内容，足够长以避免被判定为错误消息",
          references: [],
        },
      }),
    ];
    render(<ChatArea messages={messages} />);

    // 快进打字机动画（约30字符 * 15ms = 450ms）
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(screen.getByText("这是回答内容，足够长以避免被判定为错误消息")).toBeInTheDocument();
  });

  it("交替渲染用户和助手消息", () => {
    const messages: Message[] = [
      makeMessage({ id: "1", role: "user", content: "问题1" }),
      makeMessage({ id: "2", role: "assistant", content: "回答1", isStreaming: false, details: { references: [] } }),
      makeMessage({ id: "3", role: "user", content: "问题2" }),
      makeMessage({ id: "4", role: "assistant", content: "回答2", isStreaming: false, details: { references: [] } }),
    ];
    render(<ChatArea messages={messages} />);

    // 快进打字机动画
    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.getByText("问题1")).toBeInTheDocument();
    expect(screen.getByText("回答1")).toBeInTheDocument();
    expect(screen.getByText("问题2")).toBeInTheDocument();
    expect(screen.getByText("回答2")).toBeInTheDocument();
  });

  it("渲染流式中的助手消息（思考动画）", () => {
    const messages: Message[] = [
      makeMessage({
        id: "2",
        role: "assistant",
        content: "",
        isStreaming: true,
        thinkingSteps: [{ text: "正在检索文档...", state: "thinking" }],
        thinkingCollapsed: false,
      }),
    ];
    render(<ChatArea messages={messages} />);
    expect(screen.getByText("正在检索文档...")).toBeInTheDocument();
  });

  it("skipAnimation=true 的助手消息直接展示", () => {
    const messages: Message[] = [
      makeMessage({
        id: "2",
        role: "assistant",
        content: "缓存恢复的回答内容，足够长以避免被判定为错误消息",
        isStreaming: false,
        skipAnimation: true,
        details: {
          final_answer: "缓存恢复的回答内容，足够长以避免被判定为错误消息",
          references: [],
        },
      }),
    ];
    render(<ChatArea messages={messages} />);

    // 无需快进定时器，文本应立即可见
    expect(screen.getByText("缓存恢复的回答内容，足够长以避免被判定为错误消息")).toBeInTheDocument();
  });
});
