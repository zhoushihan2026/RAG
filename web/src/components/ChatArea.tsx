import { useEffect, useRef } from "react";
import type { Message } from "@/types";
import { UserMessage } from "./UserMessage";
import { AssistantMessage } from "./AssistantMessage";

interface ChatAreaProps {
  messages: Message[];
}

export function ChatArea({ messages }: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="px-6 py-6 max-w-[768px] mx-auto">
      <div className="flex flex-col gap-4">
        {messages.map((msg) =>
          msg.role === "user" ? (
            <UserMessage key={msg.id} content={msg.content} />
          ) : (
            <AssistantMessage key={msg.id} message={msg} />
          ),
        )}
      </div>
      <div ref={bottomRef} />
    </div>
  );
}
