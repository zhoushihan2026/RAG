import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { TypewriterText } from "@/components/TypewriterText";

describe("TypewriterText", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("空文本时立即完成", () => {
    const onComplete = vi.fn();
    render(<TypewriterText text="" onComplete={onComplete} />);
    expect(onComplete).toHaveBeenCalled();
  });

  it("逐字显示文本", () => {
    render(<TypewriterText text="AB" speed={10} />);

    // 快进一个字符后显示 "A"
    act(() => {
      vi.advanceTimersByTime(10);
    });
    expect(screen.getByText("A")).toBeInTheDocument();

    // 快进第二个字符后显示 "AB"
    act(() => {
      vi.advanceTimersByTime(10);
    });
    expect(screen.getByText("AB")).toBeInTheDocument();
  });

  it("完成后调用 onComplete 回调", () => {
    const onComplete = vi.fn();
    render(<TypewriterText text="Hi" speed={10} onComplete={onComplete} />);

    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(onComplete).toHaveBeenCalled();
  });

  it("打字过程中显示光标", () => {
    render(<TypewriterText text="Hello" speed={10} />);
    // 光标元素存在（inline-block w-[2px]）
    const cursor = document.querySelector(".inline-block.w-\\[2px\\]");
    expect(cursor).toBeInTheDocument();
  });

  it("完成后光标消失", () => {
    render(<TypewriterText text="Hi" speed={10} />);
    act(() => {
      vi.advanceTimersByTime(100);
    });
    const cursor = document.querySelector(".inline-block.w-\\[2px\\]");
    expect(cursor).toBeNull();
  });

  describe("skipAnimation 跳过打字机动画", () => {
    it("skipAnimation=true 时直接展示全文，不逐字播放", () => {
      render(<TypewriterText text="Hello World" speed={10} skipAnimation={true} />);

      // 无需快进定时器，文本应立即可见
      expect(screen.getByText("Hello World")).toBeInTheDocument();

      // 不应有光标（已完成状态）
      const cursor = document.querySelector(".inline-block.w-\\[2px\\]");
      expect(cursor).toBeNull();
    });

    it("skipAnimation=true 时立即调用 onComplete", () => {
      const onComplete = vi.fn();
      render(<TypewriterText text="Test" speed={10} skipAnimation={true} onComplete={onComplete} />);

      // onComplete 应在渲染时同步调用，无需等待定时器
      expect(onComplete).toHaveBeenCalledTimes(1);
    });

    it("skipAnimation=true 时不受定时器影响", () => {
      render(<TypewriterText text="ABC" speed={10} skipAnimation={true} />);

      // 快进定时器不应产生额外效果
      act(() => {
        vi.advanceTimersByTime(1000);
      });

      expect(screen.getByText("ABC")).toBeInTheDocument();
    });

    it("skipAnimation=false 时正常逐字播放（默认行为）", () => {
      render(<TypewriterText text="AB" speed={10} skipAnimation={false} />);

      // 初始不应显示完整文本
      expect(screen.queryByText("AB")).not.toBeInTheDocument();

      // 快进一个字符
      act(() => {
        vi.advanceTimersByTime(10);
      });
      expect(screen.getByText("A")).toBeInTheDocument();

      // 快进第二个字符
      act(() => {
        vi.advanceTimersByTime(10);
      });
      expect(screen.getByText("AB")).toBeInTheDocument();
    });
  });
});
