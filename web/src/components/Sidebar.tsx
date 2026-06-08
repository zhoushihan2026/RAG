import { useState, useRef, useEffect } from "react";
import type { SessionSummary } from "@/types";

// ========== SessionMenu: 三点菜单 ==========

interface SessionMenuProps {
  onRename: () => void;
  onDelete: () => void;
}

function SessionMenu({ onRename, onDelete }: SessionMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  return (
    <div ref={menuRef} className="relative">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        className="p-1 text-[#94A3B8] hover:text-[#475569] transition-colors rounded"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <circle cx="8" cy="3" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="8" cy="13" r="1.5" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 top-7 bg-white border border-[#E2E8F0] rounded-lg shadow-lg py-1 z-10 min-w-[100px]">
          <button
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
              onRename();
            }}
            className="w-full text-left px-3 py-1.5 text-[13px] text-[#475569] hover:bg-[#F1F5F9] transition-colors"
          >
            重命名
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
              onDelete();
            }}
            className="w-full text-left px-3 py-1.5 text-[13px] text-[#EF4444] hover:bg-[#FEF2F2] transition-colors"
          >
            删除
          </button>
        </div>
      )}
    </div>
  );
}

// ========== SessionItem: 单个会话条目（展开态） ==========

interface SessionItemProps {
  session: SessionSummary;
  isActive: boolean;
  onSelect: () => void;
  onRename: (newTitle: string) => void;
  onDelete: () => void;
}

function SessionItem({ session, isActive, onSelect, onRename, onDelete }: SessionItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(session.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const handleSaveRename = () => {
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== session.title) {
      onRename(trimmed);
    } else {
      setEditTitle(session.title);
    }
    setIsEditing(false);
  };

  const handleRenameClick = () => {
    setEditTitle(session.title);
    setIsEditing(true);
  };

  return (
    <div
      onClick={onSelect}
      className={`group relative flex items-center gap-2.5 px-3 py-2.5 mx-2 rounded-lg cursor-pointer transition-all duration-150 ${
        isActive
          ? "bg-[#EEF2FF]"
          : "hover:bg-[#F0F1F3]"
      }`}
    >
      {/* 激活态左侧色条 */}
      {isActive && (
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-[60%] bg-[#6366F1] rounded-r-full" />
      )}
      {/* 对话图标 */}
      <svg
        width="16"
        height="16"
        viewBox="0 0 20 20"
        fill="none"
        className={`shrink-0 ${isActive ? "text-[#6366F1]" : "text-[#9CA3AF]"}`}
      >
        <path d="M2 5a2 2 0 012-2h12a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V5z" stroke="currentColor" strokeWidth="1.5" fill="none" />
        <path d="M6 8h8M6 12h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>

      <div className="flex-1 min-w-0">
        {isEditing ? (
          <input
            ref={inputRef}
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={handleSaveRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSaveRename();
              if (e.key === "Escape") {
                setEditTitle(session.title);
                setIsEditing(false);
              }
            }}
            onClick={(e) => e.stopPropagation()}
            className="w-full text-[13px] font-medium text-[#1A1A2E] bg-white border border-[#6366F1] rounded px-1.5 py-0.5 outline-none"
          />
        ) : (
          <p className={`text-[13px] truncate ${isActive ? "font-medium text-[#1A1A2E]" : "text-[#374151]"}`}>
            {session.title}
          </p>
        )}
      </div>

      {/* hover 时显示三点菜单 */}
      <div className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
        <SessionMenu onRename={handleRenameClick} onDelete={onDelete} />
      </div>
    </div>
  );
}

// ========== CollapsedSessionItem: 折叠态会话图标 ==========

interface CollapsedSessionItemProps {
  title: string;
  isActive: boolean;
  onClick: () => void;
}

function CollapsedSessionItem({ title, isActive, onClick }: CollapsedSessionItemProps) {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <div
      className="relative flex items-center justify-center w-9 h-9 mx-auto rounded-lg cursor-pointer transition-all duration-150"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
      onClick={onClick}
      style={{ backgroundColor: isActive ? "#EEF2FF" : "transparent" }}
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 20 20"
        fill="none"
        className={isActive ? "text-[#6366F1]" : "text-[#9CA3AF]"}
      >
        <path d="M2 5a2 2 0 012-2h12a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V5z" stroke="currentColor" strokeWidth="1.5" fill="none" />
        <path d="M6 8h8M6 12h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      {/* tooltip */}
      {showTooltip && (
        <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 bg-[#1F2937] text-white text-xs px-2.5 py-1.5 rounded-md shadow-lg whitespace-nowrap z-50 max-w-[200px] truncate">
          {title}
        </div>
      )}
    </div>
  );
}

// ========== Sidebar 主组件 ==========

interface SidebarProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  collapsed: boolean;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onRenameSession: (id: string, title: string) => void;
  onDeleteSession: (id: string) => void;
}

export function Sidebar({
  sessions,
  activeSessionId,
  collapsed,
  onNewChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession,
}: SidebarProps) {
  // 展开态：260px；折叠态：56px
  return (
    <aside
      className="sidebar h-full bg-[#FAFBFC] border-r border-[#F0F1F3] flex flex-col shrink-0 overflow-hidden"
      style={{
        width: collapsed ? "56px" : "260px",
        minWidth: collapsed ? "56px" : "260px",
      }}
    >
      {/* 顶部区域：标题 + 折叠按钮 */}
      <div className="flex items-center justify-between h-12 px-3 shrink-0">
        {!collapsed && (
          <span className="text-[14px] font-semibold text-[#1A1A2E] tracking-tight">
            RAG 知识库
          </span>
        )}
        <button
          onClick={onNewChat}
          className={`flex items-center justify-center shrink-0 rounded-lg transition-all duration-150 ${
            collapsed
              ? "w-9 h-9 hover:bg-[#F0F1F3]"
              : "gap-1.5 px-3 py-1.5 border border-[#E5E7EB] hover:bg-[#F0F1F3]"
          }`}
          title="新建对话 (Ctrl+K)"
        >
          <svg
            width={collapsed ? "18" : "14"}
            height={collapsed ? "18" : "14"}
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            className="text-[#4B5563]"
          >
            <path d="M8 3v10M3 8h10" />
          </svg>
          {!collapsed && (
            <>
              <span className="text-[13px] font-medium text-[#374151]">新建对话</span>
              <span className="text-[11px] text-[#9CA3AF] font-normal">Ctrl K</span>
            </>
          )}
        </button>
      </div>

      {/* 分割线 */}
      <div className="mx-3 border-t border-[#F0F1F3]" />

      {/* 会话列表区域 */}
      <div className="flex-1 overflow-y-auto py-2">
        {collapsed ? (
          /* 折叠态：仅显示图标 */
          <div className="flex flex-col gap-1 pt-1">
            {sessions.slice(0, 8).map((session) => (
              <CollapsedSessionItem
                key={session.id}
                title={session.title}
                isActive={session.id === activeSessionId}
                onClick={() => onSelectSession(session.id)}
              />
            ))}
            {sessions.length > 8 && (
              <div className="text-center text-[10px] text-[#9CA3AF] pt-1">
                +{sessions.length - 8}
              </div>
            )}
          </div>
        ) : (
          /* 展开态：完整列表 */
          sessions.length === 0 ? (
            <div className="px-4 py-8 text-center text-[12px] text-[#9CA3AF]">
              暂无对话记录
            </div>
          ) : (
            <div className="flex flex-col gap-0.5">
              {sessions.map((session) => (
                <SessionItem
                  key={session.id}
                  session={session}
                  isActive={session.id === activeSessionId}
                  onSelect={() => onSelectSession(session.id)}
                  onRename={(title) => onRenameSession(session.id, title)}
                  onDelete={() => onDeleteSession(session.id)}
                />
              ))}
            </div>
          )
        )}
      </div>
    </aside>
  );
}
