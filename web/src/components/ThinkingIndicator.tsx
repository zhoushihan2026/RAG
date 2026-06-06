import { useMemo, useState, useEffect } from "react";
import type { ThinkingStep } from "@/types";

interface ThinkingIndicatorProps {
  thinkingSteps: ThinkingStep[];
  thinkingCollapsed: boolean;
}

/**
 * v3 思考状态指示器
 *
 * 阶段一 (thinking): 脉冲呼吸圆点 + 滚动文字带
 * 阶段二 (generating): 打字光标闪烁 + "正在生成..."
 */
export function ThinkingIndicator({
  thinkingSteps,
  thinkingCollapsed,
}: ThinkingIndicatorProps) {
  // 判断当前阶段
  const phase = useMemo<"idle" | "thinking" | "generating">(() => {
    if (thinkingSteps.length === 0) return "idle";
    if (thinkingCollapsed) return "generating";
    return "thinking";
  }, [thinkingSteps, thinkingCollapsed]);

  // 当前显示的步骤文字（用于动画过渡）
  const [displayedText, setDisplayedText] = useState("");
  const [textKey, setTextKey] = useState(0);

  // 步骤变化时触发文字滑入动画
  useEffect(() => {
    if (phase === "thinking" && thinkingSteps.length > 0) {
      const current = thinkingSteps[thinkingSteps.length - 1];
      if (current.text !== displayedText) {
        setDisplayedText(current.text);
        setTextKey((k) => k + 1);
      }
    }
  }, [phase, thinkingSteps, displayedText]);

  // idle 时不渲染
  if (phase === "idle") return null;

  return (
    <div className="flex flex-col items-start py-6">
      {phase === "thinking" ? (
        /* ===== 阶段一：思考中 - 脉冲圆点 + 滚动文字 ===== */
        <>
          {/* 脉冲呼吸圆点 */}
          <div className="flex items-center gap-2 mb-3">
            <span
              className="block w-2 h-2 rounded-full"
              style={{
                backgroundColor: "#2563EB",
                animation: "pulse-dot 1.5s ease-in-out infinite",
                animationDelay: "0s",
              }}
            />
            <span
              className="block w-2 h-2 rounded-full"
              style={{
                backgroundColor: "#8B5CF6",
                animation: "pulse-dot 1.5s ease-in-out infinite",
                animationDelay: "0.15s",
              }}
            />
            <span
              className="block w-2 h-2 rounded-full"
              style={{
                backgroundColor: "#EC4899",
                animation: "pulse-dot 1.5s ease-in-out infinite",
                animationDelay: "0.3s",
              }}
            />
          </div>
          {/* 滚动文字带 */}
          <p
            key={textKey}
            className="text-[13px] font-medium text-[#2563EB]"
            style={{ animation: "slide-in-right 0.3s ease-out forwards" }}
          >
            {displayedText}
          </p>
        </>
      ) : (
        /* ===== 阶段二：生成中 - 打字光标 + 固定文字 ===== */
        <>
          {/* 打字光标 */}
          <span
            className="inline-block w-[2px] h-[18px] bg-[#2563EB] mb-2 rounded-sm"
            style={{ animation: "cursor-pulse 1s step-end infinite" }}
          />
          {/* 固定提示文字 */}
          <p className="text-[13px] text-[#94A3B8]">正在生成回答...</p>
        </>
      )}
    </div>
  );
}
