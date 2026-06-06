import { useState, useCallback } from "react";
import type { Message, MessageDetails, ThinkingStep } from "@/types";
import { sendQuestion } from "@/api";
import { BrandBar } from "@/components/Header";
import { ChatArea } from "@/components/ChatArea";
import { WelcomeScreen } from "@/components/WelcomeScreen";
import { InputBar } from "@/components/InputBar";

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);

  const handleSubmit = useCallback(
    async (question: string) => {
      if (isGenerating || !question.trim()) return;

      setIsGenerating(true);

      // 添加用户消息
      const userMsg: Message = {
        id: generateId(),
        role: "user",
        content: question,
      };

      // 添加助手消息（初始为空，带思考步骤）
      const assistantMsg: Message = {
        id: generateId(),
        role: "assistant",
        content: "",
        isStreaming: true,
        thinkingSteps: [],
        thinkingCollapsed: false,
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);

      try {
        await sendQuestion(question, (event) => {
          switch (event.type) {
            case "status": {
              const stepText = event.content as string;
              setMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== assistantMsg.id) return m;
                  // 将之前的 thinking 步骤标记为 done，新增 thinking 步骤
                  const updatedSteps: ThinkingStep[] = [
                    ...(m.thinkingSteps || []).map((s) => ({
                      ...s,
                      state: "done" as const,
                    })),
                    { text: stepText, state: "thinking" as const },
                  ];
                  return { ...m, thinkingSteps: updatedSteps, status: stepText };
                }),
              );
              break;
            }

            case "stream_start":
              setMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== assistantMsg.id) return m;
                  // 折叠思考步骤
                  const collapsedSteps = (m.thinkingSteps || []).map((s) => ({
                    ...s,
                    state: "done" as const,
                  }));
                  return {
                    ...m,
                    status: undefined,
                    thinkingSteps: collapsedSteps,
                    thinkingCollapsed: true,
                  };
                }),
              );
              break;

            case "token":
              // v3.1: token 事件内容为 LLM JSON 中间产物，静默缓冲不渲染
              // 用户在此阶段只看到 ThinkingIndicator 的生成动画
              break;

            case "done": {
              const details = event.content as MessageDetails;
              // v3.1: 用 final_answer 替换流式累积的内容（去除中间产物 JSON）
              const finalAnswer =
                details.final_answer || "无法生成回答";
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: finalAnswer,
                        isStreaming: false,
                        status: undefined,
                        details, // 推理过程/摘要/参考来源在 details 中，由 AssistantMessage 展示
                      }
                    : m,
                ),
              );
              break;
            }

            case "error":
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: event.content as string,
                        isStreaming: false,
                        status: undefined,
                      }
                    : m,
                ),
              );
              break;
          }
        });
      } catch (err) {
        console.error("问答请求异常:", err);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? {
                  ...m,
                  content: err instanceof Error ? err.message : "请求失败，请重试",
                  isStreaming: false,
                  status: undefined,
                }
              : m,
          ),
        );
      } finally {
        setIsGenerating(false);
      }
    },
    [isGenerating],
  );

  const hasMessages = messages.length > 0;

  return (
    <div className="flex flex-col h-screen bg-white">
      <BrandBar />
      <main className="flex-1 overflow-y-auto">
        {hasMessages ? (
          <ChatArea messages={messages} />
        ) : (
          <WelcomeScreen onSelectQuestion={handleSubmit} />
        )}
      </main>
      <InputBar onSubmit={handleSubmit} isGenerating={isGenerating} />
    </div>
  );
}
