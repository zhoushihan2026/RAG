import { useState, useCallback, useEffect, useRef } from "react";
import type { Message, MessageDetails, ThinkingStep, SessionSummary, SessionMessage } from "@/types";
import { sendQuestion, getSessions, getSession, deleteSession, renameSession } from "@/api";
import { BrandBar } from "@/components/Header";
import { ChatArea } from "@/components/ChatArea";
import { WelcomeScreen } from "@/components/WelcomeScreen";
import { InputBar } from "@/components/InputBar";
import { Sidebar } from "@/components/Sidebar";

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

// 从后端 SessionMessage[] 构建完整前端 Message[]
// 尝试从 metadata 中恢复 details，避免历史消息被判定为错误（红色）
function buildMessagesFromDetail(sessionMsgs: SessionMessage[]): Message[] {
  return sessionMsgs.map((msg, idx) => ({
    id: generateId() + idx,
    role: msg.role,
    content: msg.content,
    isStreaming: false,
    // 助手消息：构造空 details 避免显示为红色错误
    // 注意：thinkingSteps 和 references 无法从后端完全恢复，但至少保证不报错样式
    ...(msg.role === "assistant" ? {
      details: {
        final_answer: msg.content,
        step_by_step_analysis: "",
        reasoning_summary: "",
        relevant_pages: [],
        source_files: {},
        references: [],
      } as MessageDetails,
      thinkingCollapsed: true,
    } : {}),
  }));
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);

  // v2 新增状态
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // 会话消息缓存：切换会话时保存/恢复完整消息状态（含 thinkingSteps、details）
  const sessionCache = useRef<Map<string, Message[]>>(new Map());

  // 用 ref 保存最新 messages，避免 useCallback 闭包捕获旧值
  const messagesRef = useRef<Message[]>(messages);
  messagesRef.current = messages;

  // 用 ref 保存最新 activeSessionId
  const activeSessionIdRef = useRef<string | null>(activeSessionId);
  activeSessionIdRef.current = activeSessionId;

  // 页面挂载时加载会话列表
  useEffect(() => {
    getSessions()
      .then((data) => {
        setSessions(data.sessions);
        // 默认选中最近一个会话
        if (data.sessions.length > 0) {
          setActiveSessionId(data.sessions[0].id);
        }
      })
      .catch(() => {
        // 后端不可用时静默处理
      });
  }, []);

  // 切换会话时加载消息（优先从缓存恢复）
  const handleSelectSession = useCallback(async (sessionId: string) => {
    if (sessionId === activeSessionIdRef.current) return;

    // 离开当前会话前，保存完整状态到缓存
    const currentId = activeSessionIdRef.current;
    if (currentId && messagesRef.current.length > 0) {
      sessionCache.current.set(currentId, messagesRef.current);
    }

    setActiveSessionId(sessionId);

    // 检查目标会话是否有缓存
    const cached = sessionCache.current.get(sessionId);
    if (cached) {
      // 缓存恢复的消息标记 skipAnimation，避免重新播放打字机动画
      const restored = cached.map((m) => ({ ...m, skipAnimation: true }));
      setMessages(restored);
      return;
    }

    // 从会话列表中查找该会话的 message_count，空会话无需请求后端
    const targetSession = sessions.find((s) => s.id === sessionId);
    if (targetSession && targetSession.message_count === 0) {
      setMessages([]);
      return;
    }

    // 无缓存则从后端加载
    try {
      const detail = await getSession(sessionId);
      const loadedMessages = buildMessagesFromDetail(detail.messages);
      sessionCache.current.set(sessionId, loadedMessages);
      setMessages(loadedMessages);
    } catch {
      setMessages([]);
    }
  }, [sessions]);  // 依赖 sessions 以获取最新的 message_count

  // 新建对话
  const handleNewChat = useCallback(() => {
    const newId = crypto.randomUUID();
    setActiveSessionId(newId);
    setMessages([]);
    // 侧边栏顶部新增一个临时会话条目
    setSessions((prev) => [
      {
        id: newId,
        title: "新对话",
        last_message: "",
        updated_at: new Date().toISOString(),
        message_count: 0,
      },
      ...prev,
    ]);
  }, []);

  // 重命名会话
  const handleRenameSession = useCallback(async (sessionId: string, title: string) => {
    // 乐观更新：先记住旧标题
    let oldTitle = "";
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id === sessionId) {
          oldTitle = s.title;
          return { ...s, title };
        }
        return s;
      }),
    );
    try {
      await renameSession(sessionId, title);
    } catch {
      // 失败时回滚到旧标题
      if (oldTitle) {
        setSessions((prev) =>
          prev.map((s) => (s.id === sessionId ? { ...s, title: oldTitle } : s)),
        );
      }
    }
  }, []);

  // 删除会话
  const handleDeleteSession = useCallback(async (sessionId: string) => {
    const confirmed = window.confirm("确定删除此对话？");
    if (!confirmed) return;

    setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    sessionCache.current.delete(sessionId);  // 清除缓存
    if (activeSessionIdRef.current === sessionId) {
      setActiveSessionId(null);
      setMessages([]);
    }
    try {
      await deleteSession(sessionId);
    } catch {
      // 静默处理
    }
  }, []);

  // 切换侧边栏
  const handleToggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => !prev);
  }, []);

  const handleSubmit = useCallback(
    async (question: string) => {
      if (isGenerating || !question.trim()) return;

      setIsGenerating(true);

      // 如果没有活跃会话，创建新会话
      let sessionId = activeSessionId;
      if (!sessionId) {
        sessionId = crypto.randomUUID();
        setActiveSessionId(sessionId);
        // 侧边栏新增条目
        setSessions((prev) => [
          {
            id: sessionId!,
            title: "新对话",
            last_message: "",
            updated_at: new Date().toISOString(),
            message_count: 0,
          },
          ...prev,
        ]);
      }

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

      // 更新侧边栏会话标题（首条用户消息前 20 字）
      const currentSessionId = sessionId;
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== currentSessionId) return s;
          const isFirstMessage = s.title === "新对话";
          return {
            ...s,
            title: isFirstMessage ? question.slice(0, 20) : s.title,
            last_message: question,
            updated_at: new Date().toISOString(),
            message_count: s.message_count + 1,
          };
        }),
      );

      try {
        await sendQuestion(question, currentSessionId, (event) => {
          switch (event.type) {
            case "status": {
              const stepText = event.content as string;
              setMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== assistantMsg.id) return m;
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
              break;

            case "done": {
              const details = event.content as MessageDetails;
              const finalAnswer =
                details.final_answer || "无法生成回答";
              setMessages((prev) => {
                const updated = prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: finalAnswer,
                        isStreaming: false,
                        status: undefined,
                        details,
                      }
                    : m,
                );
                // 回答完成后手动同步缓存
                if (currentSessionId) {
                  sessionCache.current.set(currentSessionId, updated);
                }
                return updated;
              });
              // 更新侧边栏最后消息预览
              setSessions((prev) =>
                prev.map((s) => {
                  if (s.id !== currentSessionId) return s;
                  return {
                    ...s,
                    last_message: finalAnswer.slice(0, 30),
                    updated_at: new Date().toISOString(),
                  };
                }),
              );
              break;
            }

            case "error":
              setMessages((prev) => {
                const updated = prev.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        content: typeof event.content === "string" ? event.content : "回答生成出错",
                        isStreaming: false,
                        status: undefined,
                        details: {
                          final_answer: typeof event.content === "string" ? event.content : "回答生成出错",
                          step_by_step_analysis: "",
                          reasoning_summary: "",
                          relevant_pages: [],
                          source_files: {},
                          references: [],
                        } as MessageDetails,
                      }
                    : m,
                );
                if (currentSessionId) {
                  sessionCache.current.set(currentSessionId, updated);
                }
                return updated;
              });
              break;
          }
        });
      } catch (err) {
        console.error("问答请求异常:", err);
        const errMsg = err instanceof Error ? err.message : "请求失败，请重试";
        setMessages((prev) => {
          const updated = prev.map((m) =>
            m.id === assistantMsg.id
              ? {
                  ...m,
                  content: errMsg,
                  isStreaming: false,
                  status: undefined,
                  details: {
                    final_answer: errMsg,
                    step_by_step_analysis: "",
                    reasoning_summary: "",
                    relevant_pages: [],
                    source_files: {},
                    references: [],
                  } as MessageDetails,
                }
              : m,
          );
          if (currentSessionId) {
            sessionCache.current.set(currentSessionId, updated);
          }
          return updated;
        });
      } finally {
        setIsGenerating(false);
      }
    },
    [isGenerating, activeSessionId],
  );

  const hasMessages = messages.length > 0;

  // Ctrl+K 快捷键：新建对话
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        handleNewChat();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleNewChat]);

  return (
    <div className="flex h-screen bg-white">
      {/* v2 侧边栏 */}
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        collapsed={sidebarCollapsed}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onRenameSession={handleRenameSession}
        onDeleteSession={handleDeleteSession}
      />

      {/* 主区域 */}
      <div className="flex flex-col flex-1 min-w-0">
        <BrandBar
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={handleToggleSidebar}
        />
        <main className="flex-1 overflow-y-auto">
          {hasMessages ? (
            <ChatArea messages={messages} />
          ) : (
            <WelcomeScreen onSelectQuestion={handleSubmit} />
          )}
        </main>
        <InputBar onSubmit={handleSubmit} isGenerating={isGenerating} />
      </div>
    </div>
  );
}
