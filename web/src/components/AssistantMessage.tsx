import { useState } from "react";
import type { Message } from "@/types";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { TypewriterText } from "./TypewriterText";

interface AssistantMessageProps {
  message: Message;
}

export function AssistantMessage({ message }: AssistantMessageProps) {
  const {
    content,
    isStreaming,
    details,
    thinkingSteps = [],
    thinkingCollapsed = false,
    skipAnimation = false,
  } = message;
  const [showReasoning, setShowReasoning] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  // v3.1: 打字机完成后才展示推理/参考来源；缓存恢复的消息直接展示
  const [typewriterDone, setTypewriterDone] = useState(skipAnimation);

  // 判断是否为错误消息（无 details 且内容短）
  const isError = !isStreaming && !details && content.length < 100;

  // 判断是否处于思考/生成阶段（token 阶段静默缓冲，只展示动画）
  const isThinkingOrGenerating =
    isStreaming && thinkingSteps.length > 0;

  return (
    <div className="flex justify-start">
      <div className="max-w-full text-[#1E293B]">
        {/* v3 思考/生成动画 */}
        {isThinkingOrGenerating && (
          <ThinkingIndicator
            thinkingSteps={thinkingSteps}
            thinkingCollapsed={thinkingCollapsed}
          />
        )}

        {/* v3.1 最终答案 - done 后用打字机效果逐字展示 */}
        {!isStreaming && content && !isError && (
          <div>
            {/* 答案标签 */}
            <div className="flex items-center gap-2 mb-2">
              <div className="w-[3px] h-4 bg-[#2563EB] rounded-full" />
              <span className="text-[12px] font-medium text-[#94A3B8]">
                最终答案
              </span>
            </div>
            {/* 打字机答案内容 */}
            <div className="text-[15px] leading-[1.8] text-[#1E293B]">
              <TypewriterText
                text={content}
                speed={15}
                skipAnimation={skipAnimation}
                onComplete={() => setTypewriterDone(true)}
              />
            </div>
          </div>
        )}

        {/* 错误消息 */}
        {isError && (
          <p className="text-[#EF4444] text-[14px]">{content}</p>
        )}

        {/* 分割线 + 推理过程 + 参考来源 - 打字机完成后才展示 */}
        {!isStreaming && details && typewriterDone && (
          <div className="border-t border-[#F1F5F9] mt-4 pt-3">
            {/* 推理过程（可折叠） */}
            {details.step_by_step_analysis && (
              <div className="mb-2">
                <button
                  onClick={() => setShowReasoning(!showReasoning)}
                  className="flex items-center gap-1.5 text-[13px] font-medium text-[#64748B] hover:text-[#2563EB] transition-colors"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 16 16"
                    fill="none"
                    className={`transition-transform ${showReasoning ? "rotate-90" : ""}`}
                  >
                    <path d="M6 3l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  推理过程
                </button>
                {showReasoning && (
                  <div className="mt-2 bg-[#F8FAFC] text-[#475569] text-[14px] leading-[1.8] p-3 rounded-lg">
                    {details.step_by_step_analysis}
                  </div>
                )}
              </div>
            )}

            {/* 推理摘要（可折叠） */}
            {details.reasoning_summary && (
              <div className="mb-2">
                <button
                  onClick={() => setShowSummary(!showSummary)}
                  className="flex items-center gap-1.5 text-[13px] font-medium text-[#64748B] hover:text-[#2563EB] transition-colors"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 16 16"
                    fill="none"
                    className={`transition-transform ${showSummary ? "rotate-90" : ""}`}
                  >
                    <path d="M6 3l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  推理摘要
                </button>
                {showSummary && (
                  <div className="mt-2 bg-[#F8FAFC] text-[#475569] text-[14px] leading-[1.8] p-3 rounded-lg">
                    {details.reasoning_summary}
                  </div>
                )}
              </div>
            )}

            {/* 参考来源 */}
            <div className="mt-2">
              <p className="text-[13px] font-medium text-[#64748B] mb-2">
                参考来源
              </p>
              <div className="flex flex-wrap gap-1.5">
                {details.references && details.references.length > 0 ? (
                  [...new Set(
                    details.references.map((ref) => {
                      const fileInfo =
                        details.source_files?.[ref.pdf_sha1];
                      const fileName =
                        fileInfo?.file_name || ref.source_file;
                      const shortName = fileName
                        ? fileName.replace(/\.[^.]+$/, "")
                        : ref.pdf_sha1;
                      return `${shortName} - Page ${ref.page_index}`;
                    }),
                  )].map((label) => (
                    <span
                      key={label}
                      className="inline-block bg-[#F1F5F9] text-[#475569] text-[12px] px-2.5 py-1 rounded-md"
                    >
                      {label}
                    </span>
                  ))
                ) : details.relevant_pages &&
                  details.relevant_pages.length > 0 ? (
                  details.relevant_pages.map((page) => (
                    <span
                      key={page}
                      className="inline-block bg-[#F1F5F9] text-[#475569] text-[12px] px-2.5 py-1 rounded-md"
                    >
                      Page {page}
                    </span>
                  ))
                ) : (
                  <span className="text-[#94A3B8] text-[12px]">
                    无参考来源信息
                  </span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
