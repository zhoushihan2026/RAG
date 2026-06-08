import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WelcomeScreen } from "@/components/WelcomeScreen";

describe("WelcomeScreen", () => {
  it("渲染标题和副标题", () => {
    render(<WelcomeScreen onSelectQuestion={vi.fn()} />);
    expect(screen.getByText("RAG 企业知识库问答系统")).toBeInTheDocument();
    expect(screen.getByText("基于企业年报知识库的智能问答")).toBeInTheDocument();
  });

  it("渲染三个示例问题按钮", () => {
    render(<WelcomeScreen onSelectQuestion={vi.fn()} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(3);
  });

  it("点击示例问题触发 onSelectQuestion 回调", () => {
    const onSelect = vi.fn();
    render(<WelcomeScreen onSelectQuestion={onSelect} />);
    const buttons = screen.getAllByRole("button");
    fireEvent.click(buttons[0]);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(expect.any(String));
  });
});
