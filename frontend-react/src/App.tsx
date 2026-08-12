import { useCallback, useEffect, useRef, useState } from 'react';
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
import type { ReadinessResponse } from '@/types/api';
import type { SourceDocument } from '@/types';
import { beginLogin, completeLogin, getAuthSession, isOidcConfigured } from '@/auth/oidc';
import { getMe } from '@/api/me';

interface OpenSources {
  citations: Array<Record<string, unknown>>;
  documents: SourceDocument[];
}

function LegalAssistantWorkspace() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('legal-sidebar') === 'collapsed');
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [caseDrawerOpen, setCaseDrawerOpen] = useState(false);
  const [openSources, setOpenSources] = useState<OpenSources | null>(null);
  const [readiness, setReadiness] = useState<'ready' | 'preparing' | 'missing' | 'offline'>('preparing');
  const isHealthy = readiness === 'ready';
  const isDesktop = useMediaQuery('(min-width: 1024px)');
  const isTablet = useMediaQuery('(min-width: 768px) and (max-width: 1023px)');
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const { sendMessage, stopGeneration, regenerateResponse } = useChatStream();
  const { loadSession } = useSessions();
  const {
    messages,
    isStreaming,
    streamingContent,
    statusMessage,
    activeSessionId,
    activeCase,
    workflowSteps,
    error,
    composerDraft,
    setComposerDraft,
  } = useChatStore();

  const intentLabels: Record<string, string> = {
    legal_lookup: 'Tra cứu quy định',
    legal_explain_compare: 'Giải thích hoặc so sánh',
    case_assessment: 'Kiểm tra nghĩa vụ',
    compliance_checklist: 'Lập checklist',
  };

  useEffect(() => {
    localStorage.setItem('legal-sidebar', sidebarCollapsed ? 'collapsed' : 'expanded');
  }, [sidebarCollapsed]);

  const checkHealth = useCallback(async () => {
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
        const response = await fetch(`${baseUrl}/api/v1/ready`);
        const payload = await response.json().catch(() => null) as ReadinessResponse | null;
        if (response.ok && payload?.status === 'ready') {
          setReadiness('ready');
        } else if (payload?.corpus?.status === 'missing') setReadiness('missing');
        else setReadiness('preparing');
      } catch {
        setReadiness('offline');
      }
    }, []);

  useEffect(() => {
    void checkHealth();
    const interval = window.setInterval(() => void checkHealth(), 30_000);
    return () => window.clearInterval(interval);
  }, [checkHealth]);

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
    void sendMessage(query, sessionId, 'auto', {
      intentHint: composerDraft.intent as 'auto' | 'legal_lookup' | 'legal_explain_compare' | 'case_assessment' | 'compliance_checklist',
      interactionSource: composerDraft.interactionSource as 'composer' | 'quick_action' | 'case_panel',
    });
    setComposerDraft({ text: '', intent: 'auto', interactionSource: 'composer' });
  };

  const handlePrefill = (text: string, intent: string) => {
    setComposerDraft({ text, intent, interactionSource: 'quick_action' });
  };

  const handleContinueCase = (
    facts: Record<string, string>,
    confirmationStatuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'> = {},
  ) => {
    if (!activeSessionId || !isHealthy) return;
    const prompt = activeCase?.last_query || 'Tiếp tục đánh giá tình huống này.';
    void sendMessage(prompt, activeSessionId, 'auto', {
      operation: 'continue_case',
      intentHint: activeCase?.task_type === 'build_compliance_checklist' ? 'compliance_checklist' : 'case_assessment',
      interactionSource: 'case_panel',
      casePatch: facts,
      factUpdates: Object.fromEntries(Object.entries(facts).map(([key, value]) => [key, {
        value,
        confirmation_status: confirmationStatuses[key] || 'user_confirmed',
      }])),
    });
  };

  const handleNewSession = () => {
    setOpenSources(null);
    setCaseDrawerOpen(false);
    navigate('/');
  };

  const handleRegenerate = () => {
    if (activeSessionId && isHealthy) void regenerateResponse(activeSessionId);
  };

  const handleResearch = (query: string) => {
    if (!activeSessionId || !isHealthy || !query.trim()) return;
    void sendMessage(query, activeSessionId, 'research_web');
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
          readiness={readiness}
          onOpenCase={() => setCaseDrawerOpen(true)}
          onOpenMobileNav={() => setMobileSidebarOpen(true)}
        />

        {!isHealthy && (
          <div className="flex shrink-0 items-center justify-center gap-2 border-b border-[#ead6b8] bg-[#fff8ea] px-4 py-2 text-center text-xs text-[#714b18]" role="status">
            <Icon name="wifiOff" size={15} />
            {readiness === 'missing' ? 'Thiếu dữ liệu pháp luật. Hãy chạy indexer trước khi tra cứu.' : readiness === 'preparing' ? 'Đang chuẩn bị hoặc kiểm duyệt dữ liệu pháp luật. Bạn sẽ có thể hỏi ngay khi corpus được phê duyệt.' : 'Không thể kết nối tới máy chủ. Lịch sử hiện có vẫn có thể xem, nhưng chưa thể gửi câu hỏi mới.'}
            <button className="rounded border border-[#d8b77c] px-2 py-1 font-medium hover:bg-[#fff0cf]" onClick={() => void checkHealth()} type="button">Thử lại</button>
          </div>
        )}

        {messages.length === 0 && !isStreaming ? (
          <WelcomeScreen
            disabled={!isHealthy}
            isStreaming={isStreaming}
            onSendPrompt={handleSend}
            onPrefillPrompt={handlePrefill}
            onStop={stopGeneration}
            draftText={composerDraft.text}
            onDraftChange={(text) => setComposerDraft({ text, interactionSource: 'composer' })}
            intentLabel={intentLabels[composerDraft.intent]}
            onClearIntent={() => setComposerDraft({ intent: 'auto', interactionSource: 'composer' })}
          />
        ) : (
          <>
            <WorkflowTimeline isStreaming={isStreaming} statusMessage={statusMessage} steps={workflowSteps} />
            <MessageList
              error={error}
              isStreaming={isStreaming}
              messages={messages}
              onOpenCase={activeCase ? () => setCaseDrawerOpen(true) : undefined}
              onResearch={handleResearch}
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
                  value={composerDraft.text}
                  onValueChange={(text) => setComposerDraft({ text, interactionSource: 'composer' })}
                  intentLabel={intentLabels[composerDraft.intent]}
                  onClearIntent={() => setComposerDraft({ intent: 'auto', interactionSource: 'composer' })}
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
          onContinue={handleContinueCase}
        />
      </Drawer>

      <ToastContainer />
    </div>
  );
}

export default function App() {
  const [authState, setAuthState] = useState<'ready' | 'loading' | 'error'>('loading');
  const [authError, setAuthError] = useState('');
  const initialised = useRef(false);

  const initialiseAuth = useCallback(async () => {
    if (!isOidcConfigured()) {
      setAuthState('ready');
      return;
    }
    setAuthState('loading');
    setAuthError('');
    try {
      await completeLogin();
      if (!getAuthSession()) {
        await beginLogin();
        return;
      }
      await getMe();
      setAuthState('ready');
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Không thể xác thực với SSO');
      setAuthState('error');
    }
  }, []);

  useEffect(() => {
    if (initialised.current) return;
    initialised.current = true;
    void initialiseAuth();
  }, [initialiseAuth]);

  if (isOidcConfigured() && authState !== 'ready') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#fcfcfa] p-6 text-[#172033]">
        <section className="w-full max-w-md rounded-2xl border border-[#d9e1df] bg-white p-7 shadow-sm">
          <h1 className="text-lg font-semibold">Trợ lý pháp lý EPR</h1>
          <p className="mt-2 text-sm text-[#667085]">
            {authState === 'loading' ? 'Đang xác thực tài khoản nội bộ…' : authError}
          </p>
          {authState === 'error' && (
            <button className="mt-5 rounded-lg bg-[#0f766e] px-4 py-2 text-sm font-semibold text-white" onClick={() => void initialiseAuth()} type="button">
              Đăng nhập lại
            </button>
          )}
        </section>
      </main>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<LegalAssistantWorkspace />} />
      <Route path="/conversations/:conversationId" element={<LegalAssistantWorkspace />} />
      <Route path="*" element={<LegalAssistantWorkspace />} />
    </Routes>
  );
}
