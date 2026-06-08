interface BrandBarProps {
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}

export function BrandBar({ sidebarCollapsed, onToggleSidebar }: BrandBarProps) {
  return (
    <header className="flex items-center h-12 bg-white border-b border-[#F1F5F9] shrink-0 px-4">
      {/* 汉堡按钮 - 控制侧边栏折叠/展开 */}
      <button
        onClick={onToggleSidebar}
        className="p-1.5 text-[#64748B] hover:text-[#1E293B] hover:bg-[#F1F5F9] rounded-lg transition-colors mr-3"
        title={sidebarCollapsed ? "展开侧边栏" : "折叠侧边栏"}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 12h18M3 6h18M3 18h18" />
        </svg>
      </button>
      {/* 系统名称 */}
      <h1 className="text-[14px] font-medium text-[#64748B]">
        RAG 企业知识库问答系统
      </h1>
    </header>
  );
}
