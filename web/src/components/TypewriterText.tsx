import { useState, useEffect, useRef } from "react";

interface TypewriterTextProps {
  text: string;
  speed?: number;
  onComplete?: () => void;
}

/**
 * 打字机效果组件
 *
 * v3.1: 用于在 done 事件后逐字展示最终答案
 * 模拟流式输出效果，避免直接展示 LLM JSON 中间产物
 */
export function TypewriterText({
  text,
  speed = 15,
  onComplete,
}: TypewriterTextProps) {
  const [displayedText, setDisplayedText] = useState("");
  const [isComplete, setIsComplete] = useState(false);
  const indexRef = useRef(0);

  // 用 ref 保存回调，避免因回调引用变化导致 useEffect 重启
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    // 重置状态
    setDisplayedText("");
    setIsComplete(false);
    indexRef.current = 0;

    if (!text) {
      setIsComplete(true);
      onCompleteRef.current?.();
      return;
    }

    // 打字机定时器
    const timer = setInterval(() => {
      if (indexRef.current < text.length) {
        indexRef.current += 1;
        setDisplayedText(text.slice(0, indexRef.current));
      } else {
        clearInterval(timer);
        setIsComplete(true);
        onCompleteRef.current?.();
      }
    }, speed);

    return () => clearInterval(timer);
    // 只依赖 text 和 speed，不依赖 onComplete
  }, [text, speed]);

  return (
    <span>
      {displayedText}
      {!isComplete && (
        <span
          className="inline-block w-[2px] h-[18px] bg-[#2563EB] align-middle ml-0.5"
          style={{ animation: "cursor-pulse 1s step-end infinite" }}
        />
      )}
    </span>
  );
}
