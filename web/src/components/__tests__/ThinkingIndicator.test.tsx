import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThinkingIndicator } from "@/components/ThinkingIndicator";
import type { ThinkingStep } from "@/types";

describe("ThinkingIndicator", () => {
  it("无思考步骤时不渲染", () => {
    const { container } = render(
      <ThinkingIndicator thinkingSteps={[]} thinkingCollapsed={false} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("思考阶段显示步骤文字", () => {
    const steps: ThinkingStep[] = [
      { text: "正在检索文档...", state: "thinking" },
    ];
    render(<ThinkingIndicator thinkingSteps={steps} thinkingCollapsed={false} />);
    expect(screen.getByText("正在检索文档...")).toBeInTheDocument();
  });

  it("生成阶段（collapsed）显示生成提示", () => {
    const steps: ThinkingStep[] = [
      { text: "正在检索文档...", state: "done" },
    ];
    render(<ThinkingIndicator thinkingSteps={steps} thinkingCollapsed={true} />);
    expect(screen.getByText("正在生成回答...")).toBeInTheDocument();
  });

  it("多个思考步骤时显示最新步骤文字", () => {
    const steps: ThinkingStep[] = [
      { text: "正在检索文档...", state: "done" },
      { text: "正在重排序...", state: "thinking" },
    ];
    render(<ThinkingIndicator thinkingSteps={steps} thinkingCollapsed={false} />);
    expect(screen.getByText("正在重排序...")).toBeInTheDocument();
  });
});
