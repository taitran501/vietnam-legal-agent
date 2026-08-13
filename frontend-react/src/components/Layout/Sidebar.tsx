import { useMemo, useState } from 'react';
import { useSessions } from '@/hooks/useSessions';
import { useChatStore } from '@/state/chatStore';
import { truncate } from '@/lib/formatters';
import { cn } from '@/lib/cn';
import { Modal } from '@/components/UI/Modal';
import { Icon } from '@/components/UI/Icon';
import type { SessionInfo } from '@/types';

interface SidebarProps {
  collapsed?: boolean;
  isMobile?: boolean;
  onClearAll?: () => void;
  onDismiss?: () => void;
  onNewSession?: () => void;
  onSelectSession: (sessionId: string) => void;
  onToggle?: () => void;
}

type SessionGroup = { label: string; sessions: SessionInfo[] };

function timestampMs(value: number | undefined): number {
  if (!value) return 0;
  return value < 1_000_000_000_000 ? value * 1000 : value;
}

function groupSessions(sessions: SessionInfo[]): SessionGroup[] {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups: SessionGroup[] = [
    { label: 'Hôm nay', sessions: [] },
    { label: '7 ngày trước', sessions: [] },
    { label: 'Cũ hơn', sessions: [] },
  ];

  sessions.forEach((session) => {
    const time = timestampMs(session.updated_at || session.created_at);
    const age = startOfToday - time;
    if (age <= 0) groups[0].sessions.push(session);
    else if (age <= 7 * 24 * 60 * 60 * 1000) groups[1].sessions.push(session);
    else groups[2].sessions.push(session);
  });

  return groups.filter((group) => group.sessions.length > 0);
}

export function Sidebar({
  collapsed = false,
  isMobile = false,
  onClearAll,
  onDismiss,
  onNewSession,
  onSelectSession,
  onToggle,
}: SidebarProps) {
  const {
    sessions,
    isLoadingSessions,
    searchQuery,
    setSearchQuery,
    sessionsError,
    hasMoreSessions,
    loadSessions,
    loadMoreSessions,
    deleteSession,
    clearAllSessions,
    renameSession,
  } = useSessions({ autoLoad: !collapsed || isMobile });
  const { activeSessionId } = useChatStore();
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [showClearAllModal, setShowClearAllModal] = useState(false);
  const [editingSession, setEditingSession] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const groupedSessions = useMemo(() => groupSessions(sessions), [sessions]);

  const handleNewChat = () => {
    onNewSession?.();
    onDismiss?.();
  };

  const handleSelectSession = (sessionId: string) => {
    onSelectSession(sessionId);
    onDismiss?.();
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    const deletedActiveSession = deleteTarget === activeSessionId;
    await deleteSession(deleteTarget);
    setDeleteTarget(null);
    if (deletedActiveSession) onNewSession?.();
  };

  const handleClearAllConfirm = async () => {
    await clearAllSessions();
    setShowClearAllModal(false);
    onClearAll?.();
  };

  const handleRenameStart = (event: React.MouseEvent, session: SessionInfo) => {
    event.stopPropagation();
    setEditingSession(session.id);
    setEditTitle(session.title || 'Cuộc trò chuyện mới');
  };

  const handleRenameSave = async (sessionId: string) => {
    const nextTitle = editTitle.trim();
    if (nextTitle) await renameSession(sessionId, nextTitle);
    setEditingSession(null);
    setEditTitle('');
  };

  if (collapsed && !isMobile) {
    return (
      <aside
        aria-label="Thanh điều hướng thu gọn"
        className="flex h-full w-16 flex-col items-center border-r border-[#d9e1df] bg-[#f1f4f3] py-3"
      >
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#0f766e] text-white">
          <Icon name="scale" size={21} />
        </div>
        <button
          aria-label="Mở thanh lịch sử"
          className="mt-3 rounded-md p-2 text-[#53615e] transition-colors hover:bg-[#e0e7e5] hover:text-[#172033] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]"
          onClick={onToggle}
          title="Mở thanh lịch sử"
          type="button"
        >
          <Icon name="expand" size={20} />
        </button>
        <button
          aria-label="Cuộc trò chuyện mới"
          className="mt-5 flex h-11 w-11 items-center justify-center rounded-lg bg-[#0f766e] text-white transition-colors hover:bg-[#005c55] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e] focus-visible:ring-offset-2"
          onClick={handleNewChat}
          title="Cuộc trò chuyện mới"
          type="button"
        >
          <Icon name="plus" size={22} />
        </button>
        <button
          aria-label="Lịch sử trò chuyện"
          className="mt-5 rounded-md p-2.5 text-[#53615e] transition-colors hover:bg-[#e0e7e5] hover:text-[#006a63] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]"
          onClick={onToggle}
          title="Lịch sử trò chuyện"
          type="button"
        >
          <Icon name="history" size={21} />
        </button>
      </aside>
    );
  }

  return (
    <aside aria-label="Lịch sử trò chuyện" className="flex h-full min-h-0 w-full flex-col bg-[#f1f4f3]">
      <div className="flex h-16 items-center justify-between border-b border-[#d9e1df] px-4">
        <div className="flex min-w-0 items-center gap-2.5 text-[#005c55]">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[#0f766e] text-white">
            <Icon name="scale" size={18} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">Trợ lý pháp lý</p>
            <p className="truncate text-[11px] text-[#667085]">Tra cứu có nguồn</p>
          </div>
        </div>
        <button
          aria-label={isMobile ? 'Đóng lịch sử' : 'Thu gọn thanh lịch sử'}
          className="rounded-md p-2 text-[#53615e] transition-colors hover:bg-[#e0e7e5] hover:text-[#172033] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]"
          onClick={isMobile ? onDismiss : onToggle}
          title={isMobile ? 'Đóng' : 'Thu gọn'}
          type="button"
        >
          <Icon name={isMobile ? 'close' : 'collapse'} size={20} />
        </button>
      </div>

      <div className="px-3 pt-3">
        <button
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#0f766e] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#005c55] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e] focus-visible:ring-offset-2"
          onClick={handleNewChat}
          type="button"
        >
          <Icon name="plus" size={18} />
          Cuộc trò chuyện mới
        </button>
      </div>

      <div className="px-3 pb-2 pt-3">
        <label className="relative block">
          <span className="sr-only">Tìm kiếm cuộc trò chuyện</span>
          <Icon className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#6e7977]" name="search" size={17} />
          <input
            className="w-full rounded-lg border border-transparent bg-white py-2 pl-9 pr-9 text-sm text-[#172033] outline-none placeholder:text-[#84908d] focus:border-[#0f766e] focus:ring-2 focus:ring-[#0f766e]/15"
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Tìm kiếm"
            type="search"
            value={searchQuery}
          />
          {searchQuery && (
            <button
              aria-label="Xóa nội dung tìm kiếm"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-[#6e7977] hover:bg-[#e7eceb]"
              onClick={() => setSearchQuery('')}
              type="button"
            >
              <Icon name="close" size={15} />
            </button>
          )}
        </label>
      </div>

      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3">
        {isLoadingSessions ? (
          <div className="space-y-2 px-1 py-3" aria-label="Đang tải lịch sử">
            {Array.from({ length: 5 }).map((_, index) => (
              <div className="h-11 animate-pulse rounded-md bg-[#e0e3e1]" key={index} />
            ))}
          </div>
        ) : sessionsError ? (
          <div className="px-5 py-10 text-center text-[#667085]" role="alert">
            <Icon className="mx-auto text-[#ba1a1a]" name="alert" size={25} />
            <p className="mt-3 text-sm font-medium text-[#3e4947]">Không thể tải lịch sử</p>
            <p className="mt-1 text-xs leading-5">{sessionsError}</p>
            <button
              className="mt-3 rounded-md border border-[#bdc9c6] bg-white px-3 py-2 text-xs font-semibold text-[#006a63]"
              onClick={() => void loadSessions({ reset: true })}
              type="button"
            >
              Thử lại
            </button>
          </div>
        ) : groupedSessions.length === 0 ? (
          <div className="px-5 py-12 text-center text-[#667085]">
            <Icon className="mx-auto" name={searchQuery ? 'search' : 'message'} size={25} />
            <p className="mt-3 text-sm font-medium text-[#3e4947]">
              {searchQuery ? 'Không tìm thấy cuộc trò chuyện' : 'Chưa có lịch sử'}
            </p>
            <p className="mt-1 text-xs leading-5">
              {searchQuery ? 'Thử tìm bằng từ khóa khác.' : 'Câu hỏi đầu tiên sẽ xuất hiện tại đây.'}
            </p>
          </div>
        ) : (
          groupedSessions.map((group) => (
            <section className="mt-3" key={group.label}>
              <h2 className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#667085]">
                {group.label}
              </h2>
              <div className="space-y-0.5">
                {group.sessions.map((session) => (
                  <div
                    className={cn(
                      'group relative flex cursor-pointer items-center gap-2 rounded-md border-l-2 px-2.5 py-2 text-sm transition-colors',
                      session.id === activeSessionId
                        ? 'border-[#0f766e] bg-[#e0e7e5] text-[#005c55]'
                        : 'border-transparent text-[#3e4947] hover:bg-[#e7eceb] hover:text-[#172033]'
                    )}
                    key={session.id}
                    onClick={() => handleSelectSession(session.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') handleSelectSession(session.id);
                    }}
                    role="button"
                    tabIndex={0}
                  >
                    <Icon className="shrink-0" name="message" size={16} />
                    <div className="min-w-0 flex-1">
                      {editingSession === session.id ? (
                        <input
                          autoFocus
                          className="w-full rounded border border-[#0f766e] bg-white px-2 py-1 text-sm text-[#172033] outline-none ring-2 ring-[#0f766e]/15"
                          onBlur={() => void handleRenameSave(session.id)}
                          onChange={(event) => setEditTitle(event.target.value)}
                          onClick={(event) => event.stopPropagation()}
                          onKeyDown={(event) => {
                            event.stopPropagation();
                            if (event.key === 'Enter') void handleRenameSave(session.id);
                            if (event.key === 'Escape') setEditingSession(null);
                          }}
                          value={editTitle}
                        />
                      ) : (
                        <p className="truncate font-medium">{truncate(session.title || 'Cuộc trò chuyện mới', 34)}</p>
                      )}
                    </div>
                    {editingSession !== session.id && (
                      <div className="flex shrink-0 items-center opacity-100 sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
                        <button
                          aria-label="Đổi tên cuộc trò chuyện"
                          className="rounded p-1.5 text-[#667085] hover:bg-white hover:text-[#172033]"
                          onClick={(event) => handleRenameStart(event, session)}
                          title="Đổi tên"
                          type="button"
                        >
                          <Icon name="edit" size={14} />
                        </button>
                        <button
                          aria-label="Xóa cuộc trò chuyện"
                          className="rounded p-1.5 text-[#667085] hover:bg-[#fff0ef] hover:text-[#ba1a1a]"
                          onClick={(event) => {
                            event.stopPropagation();
                            setDeleteTarget(session.id);
                          }}
                          title="Xóa"
                          type="button"
                        >
                          <Icon name="trash" size={14} />
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          ))
        )}
        {!sessionsError && hasMoreSessions && (
          <div className="px-2 py-3 text-center">
            <button
              className="rounded-md border border-[#bdc9c6] bg-white px-3 py-2 text-xs font-semibold text-[#006a63] disabled:opacity-60"
              disabled={isLoadingSessions}
              onClick={() => void loadMoreSessions()}
              type="button"
            >
              {isLoadingSessions ? 'Đang tải…' : 'Tải thêm'}
            </button>
          </div>
        )}
      </div>

      {sessions.length > 0 && (
        <div className="border-t border-[#d9e1df] px-3 py-3 text-right">
          <button
            className="rounded-md px-2 py-1.5 text-xs font-medium text-[#8f2424] hover:bg-[#fff0ef]"
            onClick={() => setShowClearAllModal(true)}
            type="button"
          >
            Xóa toàn bộ
          </button>
        </div>
      )}

      <Modal
        cancelText="Hủy"
        confirmText="Xóa"
        isOpen={!!deleteTarget}
        message="Hành động này không thể hoàn tác."
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => void handleDeleteConfirm()}
        title="Xóa cuộc trò chuyện này?"
        variant="danger"
      />
      <Modal
        cancelText="Hủy"
        confirmText="Xóa tất cả"
        isOpen={showClearAllModal}
        message="Toàn bộ lịch sử trò chuyện sẽ bị xóa và không thể khôi phục."
        onClose={() => setShowClearAllModal(false)}
        onConfirm={() => void handleClearAllConfirm()}
        title="Xóa tất cả cuộc trò chuyện?"
        variant="danger"
      />
    </aside>
  );
}
