interface UserMessageProps {
  content: string;
}

export function UserMessage({ content }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[75%] bg-[#2563EB] text-white text-[14px] leading-[1.6] px-4 py-2.5 rounded-2xl rounded-br-sm">
        {content}
      </div>
    </div>
  );
}
