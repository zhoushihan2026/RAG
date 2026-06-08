import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { UserMessage } from "@/components/UserMessage";

describe("UserMessage", () => {
  it("渲染用户消息内容", () => {
    render(<UserMessage content="你好" />);
    expect(screen.getByText("你好")).toBeInTheDocument();
  });

  it("长内容也能正常渲染", () => {
    const longText = "这是一段很长的用户消息".repeat(10);
    render(<UserMessage content={longText} />);
    expect(screen.getByText(longText)).toBeInTheDocument();
  });
});
