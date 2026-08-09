import { useEffect, useState } from 'react';
import { Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ChatInput } from '@/components/Chat/ChatInput';
import { MessageList } from '@/components/Chat/MessageList';
import { SourceDrawer } from '@/components/Chat/SourceDrawer';
import { WelcomeScreen } from '@/components/Onboarding/WelcomeScreen';
import { Sidebar } from '@/components/Layout/Sidebar';
import { Header } from '@/components/Layout/Header';
import { ToastContainer } from '@/components/UI/Toast';
import { Drawer } from '@/components/UI/Drawer';
import { Icon } from '@/components/UI/Icon';
import { WorkflowTimeline } from '@/components/Agent/WorkflowTimeline';
import { CaseFactsPanel } from '@/components/Case/CaseFactsPanel';
import { useChatStream } from '@/hooks/useChatStream';
import { useSessions } from '@/hooks/useSessions';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { useChatStore } from '@/state/chatStore';
import type { SourceDocument } from '@/types';

const FAQ_THRESHOLD = 0.75;

interface OpenSources {
  citations: Array<Record<string, unknown>>;
  documents: SourceDocument[];
}

function LegalAssistantWorkspace() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('legal-sidebar') === 'collapsed');
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [caseDrawerOpen, setCaseDrawerOpen] = useState(false);
  const [openSources, setOpenSources] = useState<OpenSources | null>(null);
  const [isHealthy, setIsHealthy] = useState(true);
  const isDesktop = useMediaQuery('(min-width: 1024px)');
  const isTablet = useMediaQuery('(min-width: 768px) and (max-width: 1023px)');
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const { sendMessage, stopGeneration, regenerateResponse } = useChatStream();
  const { loadSession, loadSessions } = useSessions();
  const {
    messages,
    isStreaming,
    streamingContent,
    statusMessage,
    activeSessionId,
    activeCase,
    workflowSteps,
    error,
  } = useChatStore();

  useEffect(() => {
    localStorage.setItem('legal-sidebar', sidebarCollapsed ? 'collapsed' : 'expanded');
  }, [sidebarCollapsed]);

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
        const response = await fetch(`${baseUrl}/api/v1/health`);
        setIsHealthy(response.ok);
        if (response.ok) void loadSessions();
      } catch {
        setIsHealthy(false);
      }
    };
    void checkHealth();
    const interval = window.setInterval(() => void checkHealth(), 30_000);
    return () => window.clearInterval(interval);
  }, [loadSessions]);

  useEffect(() => {
    if (conversationId && conversationId !== activeSessionId) void loadSession(conversationId);
  }, [activeSessionId, conversationId, loadSession]);

  useEffect(() => {
    setOpenSources(null);
    setCaseDrawerOpen(false);
  }, [activeSessionId]);

  const handleSend = (query: string) => {
    if (!isHealthy) return;
    let sessionId = activeSessionId;
    if (!sessionId) {
      sessionId = crypto.randomUUID();
      useChatStore.getState().setActiveSession(sessionId);
      navigate(`/conversations/${sessionId}`);
    }
    void sendMessage(query, sessionId, FAQ_THRESHOLD);
  };

  const handleNewSession = () => {
    setOpenSources(null);
    setCaseDrawerOpen(false);
    navigate('/');
  };

  const handleRegenerate = () => {
    if (activeSessionId && isHealthy) void regenerateResponse(activeSessionId, FAQ_THRESHOLD);
  };

  const handleOpenSources = (
    documents: SourceDocument[],
    citations: Array<Record<string, unknown>>
  ) => {
    if (documents.length || citations.length) setOpenSources({ documents, citations });
  };

  useKeyboardShortcuts({ onStop: stopGeneration, isStreaming });

  const sharedSidebarProps = {
    onSelectSession: (sessionId: string) => navigate(`/conversations/${sessionId}`),
    onClearAll: handleNewSession,
    onNewSession: handleNewSession,
  };

  return (
    <div className="flex h-[100dvh] min-h-0 overflow-hidden bg-[#fcfcfa] text-[#181c1c]">
      {(isDesktop || isTablet) && (
        <div
          className={`flex h-full shrink-0 overflow-hidden transition-[width] duration-200 ease-out ${
            isTablet || sidebarCollapsed ? 'w-16' : 'w-[264px]'
          }`}
        >
          <Sidebar
            {...sharedSidebarProps}
            collapsed={isTablet || sidebarCollapsed}
            onToggle={isTablet ? () => setMobileSidebarOpen(true) : () => setSidebarCollapsed((value) => !value)}
          />
        </div>
      )}

      {mobileSidebarOpen && (
        <div className="fixed inset-0 z-30 lg:hidden">
          <button
            aria-label="Đóng lịch sử trò chuyện"
            className="absolute inset-0 h-full w-full bg-slate-950/25 backdrop-blur-[1px] motion-safe:animate-[fadeIn_180ms_ease-out]"
            onClick={() => setMobileSidebarOpen(false)}
            type="button"
          />
          <div className="absolute inset-y-0 left-0 w-[min(304px,calc(100vw-48px))] shadow-[12px_0_32px_rgba(24,28,28,0.10)] motion-safe:animate-[sidebarIn_200ms_cubic-bezier(0.4,0,0.2,1)]">
            <Sidebar
              {...sharedSidebarProps}
              isMobile
              onDismiss={() => setMobileSidebarOpen(false)}
            />
          </div>
        </div>
      )}

      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-[#fcfcfa]">
        <Header
          hasActiveCase={Boolean(activeCase)}
          isHealthy={isHealthy}
          onOpenCase={() => setCaseDrawerOpen(true)}
          onOpenMobileNav={() => setMobileSidebarOpen(true)}
        />

        {!isHealthy && (
          <div className="flex shrink-0 items-center justify-center gap-2 border-b border-[#ead6b8] bg-[#fff8ea] px-4 py-2 text-center text-xs text-[#714b18]" role="status">
            <Icon name="wifiOff" size={15} />
            Không thể kết nối tới máy chủ. Lịch sử hiện có vẫn có thể xem, nhưng chưa thể gửi câu hỏi mới.
          </div>
        )}

        {messages.length === 0 && !isStreaming ? (
          <WelcomeScreen
            disabled={!isHealthy}
            isStreaming={isStreaming}
            onSendPrompt={handleSend}
            onStop={stopGeneration}
          />
        ) : (
          <>
            <WorkflowTimeline isStreaming={isStreaming} statusMessage={statusMessage} steps={workflowSteps} />
            <MessageList
              error={error}
              isStreaming={isStreaming}
              messages={messages}
              onOpenCase={activeCase ? () => setCaseDrawerOpen(true) : undefined}
              onOpenSources={handleOpenSources}
              onRegenerate={handleRegenerate}
              statusMessage={statusMessage}
              streamingContent={streamingContent}
            />
            <div className="shrink-0 border-t border-[#d9e1df] bg-[#fcfcfa]/95 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur sm:px-6">
              <div className="mx-auto flex max-w-[820px] justify-center">
                <ChatInput
                  disabled={!isHealthy}
                  isStreaming={isStreaming}
                  onSend={handleSend}
                  onStop={stopGeneration}
                />
              </div>
            </div>
          </>
        )}
      </main>

      <SourceDrawer
        citations={openSources?.citations}
        documents={openSources?.documents || []}
        isOpen={Boolean(openSources)}
        onClose={() => setOpenSources(null)}
      />

      <Drawer
        description="Bảng này chỉ xuất hiện với tác vụ đánh giá hoặc checklist EPR cần dữ liệu doanh nghiệp."
        isOpen={caseDrawerOpen && Boolean(activeCase)}
        onClose={() => setCaseDrawerOpen(false)}
        title="Thông tin tình huống"
      >
        <CaseFactsPanel
          caseState={activeCase}
          conversationId={activeSessionId}
          onCaseChange={(caseState) => useChatStore.getState().setActiveCase(caseState)}
        />
      </Drawer>

      <ToastContainer />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LegalAssistantWorkspace />} />
      <Route path="/conversations/:conversationId" element={<LegalAssistantWorkspace />} />
      <Route path="*" element={<LegalAssistantWorkspace />} />
    </Routes>
  );
}
