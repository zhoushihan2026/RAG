import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { AssistantMessage } from "@/components/AssistantMessage";
import type { Message } from "@/types";

// mock scrollIntoView（jsdom 不支持）
Element.prototype.scrollIntoView = vi.fn();

// 辅助函数：构造助手消息
function makeAssistantMsg(overrides: Partial<Message> = {}): Message {
  return {
    id: "test-assistant",
    role: "assistant",
    content: "",
    isStreaming: false,
    ...overrides,
  };
}

describe("AssistantMessage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("渲染已完成的最终答案（有 details，内容长）", () => {
    const msg = makeAssistantMsg({
      content: "这是最终答案，内容足够长以避免被判定为错误消息",
      isStreaming: false,
      details: {
        final_answer: "这是最终答案，内容足够长以避免被判定为错误消息",
        references: [],
      },
    });
    render(<AssistantMessage message={msg} />);

    // 快进打字机动画（约30字符 * 15ms = 450ms）
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(screen.getByText("最终答案")).toBeInTheDocument();
    expect(screen.getByText("这是最终答案，内容足够长以避免被判定为错误消息")).toBeInTheDocument();
  });

  it("流式中且有思考步骤时显示思考动画", () => {
    const msg = makeAssistantMsg({
      content: "",
      isStreaming: true,
      thinkingSteps: [{ text: "正在检索...", state: "thinking" }],
      thinkingCollapsed: false,
    });
    render(<AssistantMessage message={msg} />);
    expect(screen.getByText("正在检索...")).toBeInTheDocument();
  });

  it("错误消息显示红色文字", () => {
    // isError: !isStreaming && !details && content.length < 100
    const msg = makeAssistantMsg({
      content: "请求失败",
      isStreaming: false,
      // 不提供 details
    });
    render(<AssistantMessage message={msg} />);
    const errorEl = screen.getByText("请求失败");
    expect(errorEl.className).toContain("text-[#EF4444]");
  });

  it("打字机完成后可展开推理过程", () => {
    const msg = makeAssistantMsg({
      content: "AB",
      isStreaming: false,
      details: {
        final_answer: "AB",
        step_by_step_analysis: "推理过程详细内容",
        references: [],
      },
    });
    render(<AssistantMessage message={msg} />);

    // 快进打字机动画（2字符 * 15ms = 30ms）
    act(() => {
      vi.advanceTimersByTime(100);
    });

    // 推理过程按钮出现
    const reasoningBtn = screen.getByText("推理过程");
    expect(reasoningBtn).toBeInTheDocument();

    // 点击展开
    fireEvent.click(reasoningBtn);
    expect(screen.getByText("推理过程详细内容")).toBeInTheDocument();
  });

  it("打字机完成前不显示推理过程和参考来源", () => {
    const msg = makeAssistantMsg({
      content: "很长的答案内容" + "x".repeat(200),
      isStreaming: false,
      details: {
        final_answer: "答案",
        step_by_step_analysis: "推理",
        references: [],
      },
    });
    render(<AssistantMessage message={msg} />);

    // 打字机未完成时，不应出现推理过程按钮
    expect(screen.queryByText("推理过程")).not.toBeInTheDocument();
  });

  it("有参考来源时显示来源标签", () => {
    const msg = makeAssistantMsg({
      content: "AB",
      isStreaming: false,
      details: {
        final_answer: "AB",
        references: [
          { pdf_sha1: "abc123", page_index: 5, source_file: "report.pdf" },
        ],
        source_files: {
          abc123: { file_name: "report.pdf", company_name: "测试公司" },
        },
      },
    });
    render(<AssistantMessage message={msg} />);

    // 快进打字机（2字符 * 15ms = 30ms）
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(screen.getByText(/report - Page 5/)).toBeInTheDocument();
  });

  it("无参考来源时显示无参考来源信息", () => {
    const msg = makeAssistantMsg({
      content: "AB",
      isStreaming: false,
      details: {
        final_answer: "AB",
        references: [],
      },
    });
    render(<AssistantMessage message={msg} />);

    // 快进打字机
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(screen.getByText("无参考来源信息")).toBeInTheDocument();
  });

  describe("skipAnimation 缓存恢复消息跳过动画", () => {
    it("skipAnimation=true 时直接展示全文，无需等待打字机", () => {
      const msg = makeAssistantMsg({
        content: "缓存恢复的答案内容，足够长以避免被判定为错误消息",
        isStreaming: false,
        skipAnimation: true,
        details: {
          final_answer: "缓存恢复的答案内容，足够长以避免被判定为错误消息",
          references: [],
        },
      });
      render(<AssistantMessage message={msg} />);

      // 无需快进定时器，文本应立即可见
      expect(screen.getByText("缓存恢复的答案内容，足够长以避免被判定为错误消息")).toBeInTheDocument();
    });

    it("skipAnimation=true 时推理过程和参考来源立即显示", () => {
      const msg = makeAssistantMsg({
        content: "缓存恢复的答案内容，足够长以避免被判定为错误消息",
        isStreaming: false,
        skipAnimation: true,
        details: {
          final_answer: "缓存恢复的答案内容，足够长以避免被判定为错误消息",
          step_by_step_analysis: "推理过程内容",
          references: [],
        },
      });
      render(<AssistantMessage message={msg} />);

      // skipAnimation=true 时 typewriterDone 初始为 true，推理过程应立即可见
      expect(screen.getByText("推理过程")).toBeInTheDocument();
    });

    it("skipAnimation=false 时推理过程需等待打字机完成", () => {
      const msg = makeAssistantMsg({
        content: "AB",
        isStreaming: false,
        skipAnimation: false,
        details: {
          final_answer: "AB",
          step_by_step_analysis: "推理过程内容",
          references: [],
        },
      });
      render(<AssistantMessage message={msg} />);

      // 打字机未完成时，不应出现推理过程按钮
      expect(screen.queryByText("推理过程")).not.toBeInTheDocument();

      // 快进打字机完成后（2字符 * 15ms = 30ms），推理过程出现
      act(() => {
        vi.advanceTimersByTime(100);
      });
      expect(screen.getByText("推理过程")).toBeInTheDocument();
    });
  });
});
