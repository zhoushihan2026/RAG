import { useState, useEffect, useRef, useMemo } from "react";

interface TypewriterTextProps {
  text: string;
  speed?: number;
  skipAnimation?: boolean;  // 跳过打字机效果，直接展示全文
  onComplete?: () => void;
}

/**
 * 将简单 Markdown 文本转换为 HTML
 * 支持：加粗(**text**)、换行、列表(- item)、标题(##)
 */
function simpleMarkdown(text: string): string {
  let html = text;

  // 转义 HTML 特殊字符（但保留后续替换的标签）
  html = html.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  // 加粗 **text**
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // 标题 ## text
  html = html.replace(/^## (.+)$/gm, "<h3 class='text-base font-semibold mt-3 mb-1'>$1</h3>");
  html = html.replace(/^### (.+)$/gm, "<h4 class='text-sm font-semibold mt-2 mb-1'>$1</h4>");

  // 无序列表 - item
  html = html.replace(/^- (.+)$/gm, "<li class='ml-4 list-disc'>$1</li>");

  // 有序列表 1. item
  html = html.replace(/^\d+\. (.+)$/gm, "<li class='ml-4 list-decimal'>$1</li>");

  // 连续的 li 包裹在 ul 中
  html = html.replace(/((?:<li class='ml-4 list-disc'>.*<\/li>\n?)+)/g, "<ul class='my-1'>$1</ul>");
  html = html.replace(/((?:<li class='ml-4 list-decimal'>.*<\/li>\n?)+)/g, "<ol class='my-1'>$1</ol>");

  // 换行：双换行变段落，单换行变 <br>
  html = html.replace(/\n\n/g, "</p><p class='mt-2'>");
  html = html.replace(/\n/g, "<br/>");

  // 包裹在段落中
  html = `<p>${html}</p>`;

  // 清理空段落
  html = html.replace(/<p>\s*<\/p>/g, "");

  return html;
}

/**
 * 打字机效果组件
 *
 * v3.1: 用于在 done 事件后逐字展示最终答案
 * 模拟流式输出效果，避免直接展示 LLM JSON 中间产物
 * skipAnimation=true 时直接展示全文（用于缓存恢复的历史消息）
 * 支持 Markdown 渲染（加粗、换行、列表）
 */
export function TypewriterText({
  text,
  speed = 15,
  skipAnimation = false,
  onComplete,
}: TypewriterTextProps) {
  const [displayedText, setDisplayedText] = useState("");
  const [isComplete, setIsComplete] = useState(false);
  const indexRef = useRef(0);

  // 用 ref 保存回调，避免因回调引用变化导致 useEffect 重启
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    // 跳过动画：直接展示全文
    if (skipAnimation) {
      setDisplayedText(text);
      setIsComplete(true);
      onCompleteRef.current?.();
      return;
    }

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
  }, [text, speed, skipAnimation]);

  // 对已展示的文本做 Markdown 渲染
  const renderedHtml = useMemo(() => simpleMarkdown(displayedText), [displayedText]);

  return (
    <span>
      <span dangerouslySetInnerHTML={{ __html: renderedHtml }} />
      {!isComplete && (
        <span
          className="inline-block w-[2px] h-[18px] bg-[#2563EB] align-middle ml-0.5"
          style={{ animation: "cursor-pulse 1s step-end infinite" }}
        />
      )}
    </span>
  );
}
