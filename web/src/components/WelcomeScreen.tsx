interface WelcomeScreenProps {
  onSelectQuestion: (question: string) => void;
}

const EXAMPLE_QUESTIONS = [
  "中芯国际2024年研发投入占营业收入的比例是多少？",
  "东方证券对中芯国际的评级是什么？",
  "中芯国际2024年营收情况如何？",
];

export function WelcomeScreen({ onSelectQuestion }: WelcomeScreenProps) {
  return (
    <div className="flex items-center justify-center h-full px-6">
      <div className="text-center max-w-[600px]">
        <h2 className="text-[28px] font-semibold text-[#1E293B] mb-3">
          RAG 企业知识库问答系统
        </h2>
        <p className="text-[15px] text-[#64748B] mb-2">
          基于企业年报知识库的智能问答
        </p>
        <p className="text-[13px] text-[#94A3B8] mb-8">
          在下方输入框中输入问题开始对话
        </p>
        <div className="flex flex-col gap-2 items-center">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => onSelectQuestion(q)}
              className="w-full max-w-[480px] text-left px-4 py-3 text-[13px] text-[#475569] bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl hover:border-[#2563EB] hover:bg-white transition-colors"
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
