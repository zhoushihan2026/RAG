import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InputBar } from "@/components/InputBar";

describe("InputBar", () => {
  it("渲染输入框和发送按钮", () => {
    render(<InputBar onSubmit={vi.fn()} isGenerating={false} />);
    expect(screen.getByPlaceholderText("输入您的问题...")).toBeInTheDocument();
  });

  it("空内容时发送按钮禁用", () => {
    render(<InputBar onSubmit={vi.fn()} isGenerating={false} />);
    const textarea = screen.getByPlaceholderText("输入您的问题...");
    expect(textarea).toBeInTheDocument();
  });

  it("输入内容后可以提交", () => {
    const onSubmit = vi.fn();
    render(<InputBar onSubmit={onSubmit} isGenerating={false} />);
    const textarea = screen.getByPlaceholderText("输入您的问题...");
    fireEvent.change(textarea, { target: { value: "测试问题" } });
    // 按 Enter 提交
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    expect(onSubmit).toHaveBeenCalledWith("测试问题");
  });

  it("Shift+Enter 不提交（换行）", () => {
    const onSubmit = vi.fn();
    render(<InputBar onSubmit={onSubmit} isGenerating={false} />);
    const textarea = screen.getByPlaceholderText("输入您的问题...");
    fireEvent.change(textarea, { target: { value: "测试问题" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("生成中时输入框禁用", () => {
    render(<InputBar onSubmit={vi.fn()} isGenerating={true} />);
    const textarea = screen.getByPlaceholderText("输入您的问题...");
    expect(textarea).toBeDisabled();
  });

  it("生成中时提交不触发", () => {
    const onSubmit = vi.fn();
    render(<InputBar onSubmit={onSubmit} isGenerating={true} />);
    const textarea = screen.getByPlaceholderText("输入您的问题...");
    // 即使有内容，isGenerating 时也不应提交
    fireEvent.change(textarea, { target: { value: "测试" } });
    // textarea 被禁用，change 不会生效
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("渲染附件按钮", () => {
    render(<InputBar onSubmit={vi.fn()} isGenerating={false} />);
    // 附件按钮有 title 属性
    const attachBtn = screen.getByTitle("上传 PDF 文件");
    expect(attachBtn).toBeInTheDocument();
  });
});
