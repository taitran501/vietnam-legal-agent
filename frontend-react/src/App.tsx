import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
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
import { GuidedCaseCard } from '@/components/Case/GuidedCaseCard';
import { useChatStream } from '@/hooks/useChatStream';
import { useSessions } from '@/hooks/useSessions';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { useChatStore } from '@/state/chatStore';
import { useAuthStore } from '@/state/authStore';
import { toast } from '@/state/toastStore';
import type { CaseFormState, CaseState, ReadinessResponse, SourceDocument } from '@/types';
import {
  AUTH_EXPIRED_EVENT,
  beginLogin,
  clearAuthSession,
  completeLogin,
  getAuthSession,
  isOidcConfigured,
  rememberReturnTo,
} from '@/auth/oidc';
import { getMe } from '@/api/me';

interface OpenSources {
  citations: Array<Record<string, unknown>>;
  documents: SourceDocument[];
  focusIndex?: number;
  preview?: boolean;
}

interface WorkspaceProps {
  onLogout?: () => void;
}

let pendingLocalSessionId: string | null = null;

type GuidedDraftSnapshot = {
  taskType: CaseState['task_type'];
  facts: Record<string, string>;
  statuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>;
  formState: CaseFormState | null;
};

function capabilityStatus(readiness: ReadinessResponse | null, name: keyof ReadinessResponse['capabilities']) {
  return readiness?.capabilities?.[name]?.status
    || (readiness?.status === 'ready' ? 'ready' : 'blocked');
}

function readinessMessage(readiness: ReadinessResponse | null, offline: boolean): string {
  if (offline) return 'Không thể kết nối tới máy chủ. Lịch sử đã tải vẫn được giữ, nhưng chưa thể gửi câu hỏi mới.';
  const reason = readiness?.capabilities?.legal_chat?.reason || '';
  const messages: Record<string, string> = {
    database_schema_mismatch: 'Cơ sở dữ liệu lịch sử chưa tương thích. Quản trị viên cần chạy lệnh migration được hướng dẫn trên backend.',
    corpus_promotion_blocked: 'Kho văn bản chưa được phê duyệt nên kết luận pháp lý đang tạm khóa.',
    corpus_not_ready: 'Kho văn bản pháp luật chưa sẵn sàng. Lịch sử và tài khoản vẫn có thể sử dụng.',
    qdrant_unavailable: 'Kho tìm kiếm pháp luật đang tạm thời không khả dụng.',
  };
  return messages[reason] || 'Khả năng tra cứu pháp luật đang chuẩn bị. Lịch sử và tài khoản vẫn có thể sử dụng.';
}

function LegalAssistantWorkspace({ onLogout }: WorkspaceProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('legal-sidebar') === 'collapsed');
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [caseDrawerOpen, setCaseDrawerOpen] = useState(false);
  const [guidedTask, setGuidedTask] = useState<CaseState['task_type'] | null>(null);
  const [guidedDraft, setGuidedDraft] = useState<GuidedDraftSnapshot | null>(null);
  const [caseDirty, setCaseDirty] = useState(false);
  const [openSources, setOpenSources] = useState<OpenSources | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [readinessOffline, setReadinessOffline] = useState(false);
  const isDesktop = useMediaQuery('(min-width: 1024px)');
  const isTablet = useMediaQuery('(min-width: 768px) and (max-width: 1023px)');
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const { sendMessage, stopGeneration, regenerateResponse, retryLastTurn } = useChatStream();
  const { loadSession, cancelSessionLoad } = useSessions({ autoLoad: false });
  const me = useAuthStore((state) => state.me);
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
    sessionLoadStatus,
    sessionLoadError,
    setComposerDraft,
  } = useChatStore();

  const legalReady = !readinessOffline && capabilityStatus(readiness, 'legal_chat') === 'ready';
  const caseReady = !readinessOffline && capabilityStatus(readiness, 'case_workflow') === 'ready';
  const webReady = !readinessOffline && capabilityStatus(readiness, 'web_research') === 'ready';
  const preview = Boolean(readiness?.preview || readiness?.runtime_mode === 'preview');
  const headerReadiness: 'ready' | 'preview' | 'blocked' | 'preparing' | 'offline' = readinessOffline
    ? 'offline'
    : !readiness
      ? 'preparing'
      : preview && legalReady
        ? 'preview'
        : legalReady
          ? 'ready'
          : 'blocked';
  const lastAssistantStatus = [...messages].reverse().find((message) => message.role === 'assistant')?.status;

  const intentLabels: Record<string, string> = {
    legal_lookup: 'Tra cứu quy định',
    legal_explain_compare: 'Giải thích hoặc so sánh',
    case_assessment: 'Kiểm tra trường hợp',
    compliance_checklist: 'Danh sách việc cần làm',
  };

  useEffect(() => {
    localStorage.setItem('legal-sidebar', sidebarCollapsed ? 'collapsed' : 'expanded');
  }, [sidebarCollapsed]);

  const checkHealth = useCallback(async () => {
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const response = await fetch(`${baseUrl}/api/v1/ready`);
      const payload = await response.json().catch(() => null) as ReadinessResponse | null;
      if (payload?.capabilities || payload?.status) {
        setReadiness(payload);
        setReadinessOffline(false);
        return;
      }
      throw new Error(`Unexpected readiness response: ${response.status}`);
    } catch {
      setReadinessOffline(true);
    }
  }, []);

  useEffect(() => {
    void checkHealth();
    const interval = window.setInterval(() => void checkHealth(), 30_000);
    return () => window.clearInterval(interval);
  }, [checkHealth]);

  const loadConversationFromRoute = useCallback(async (sessionId: string) => {
    const result = await loadSession(sessionId);
    if (result === 'not_found') {
      toast.info('Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.');
      navigate('/', { replace: true });
    }
  }, [loadSession, navigate]);

  useLayoutEffect(() => {
    setOpenSources(null);
    setCaseDrawerOpen(false);
    setCaseDirty(false);
    const current = useChatStore.getState();
    if (!conversationId) {
      setGuidedTask(null);
      setGuidedDraft(null);
      cancelSessionLoad();
      if (current.activeTurn) stopGeneration();
      current.clearChat();
      return;
    }

    if (current.activeTurn && current.activeTurn.conversationId !== conversationId) stopGeneration();
    if (pendingLocalSessionId === conversationId && current.activeSessionId === conversationId) {
      pendingLocalSessionId = null;
      return;
    }
    setGuidedTask(null);
    setGuidedDraft(null);
    void loadConversationFromRoute(conversationId);
    return cancelSessionLoad;
  }, [cancelSessionLoad, conversationId, loadConversationFromRoute, stopGeneration]);

  const handleSend = (query: string) => {
    if (!legalReady) {
      toast.info(readinessMessage(readiness, readinessOffline));
      return;
    }
    let sessionId = activeSessionId;
    if (!sessionId) {
      sessionId = crypto.randomUUID();
      pendingLocalSessionId = sessionId;
      useChatStore.getState().setActiveSession(sessionId);
      navigate(`/conversations/${sessionId}`);
    }
    void sendMessage(query, sessionId, 'auto', {
      operation: 'message',
      intentHint: composerDraft.intent as 'auto' | 'legal_lookup' | 'legal_explain_compare' | 'case_assessment' | 'compliance_checklist',
      interactionSource: composerDraft.interactionSource as 'composer' | 'quick_action' | 'case_panel' | 'guided_form',
    });
    setComposerDraft({ text: '', intent: 'auto', interactionSource: 'composer' });
  };

  const handlePrefill = (text: string, intent: string) => {
    setComposerDraft({ text, intent, interactionSource: 'quick_action' });
  };

  const handleGuidedDraftChange = useCallback((facts: Record<string, string>, statuses: GuidedDraftSnapshot['statuses'], formState: CaseFormState | null) => {
    if (!guidedTask) return;
    setGuidedDraft({ taskType: guidedTask, facts, statuses, formState });
  }, [guidedTask]);

  const handleRecoveryDraftChange = useCallback((facts: Record<string, string>, statuses: GuidedDraftSnapshot['statuses'], formState: CaseFormState | null) => {
    setGuidedDraft((current) => current ? { ...current, facts, statuses, formState } : current);
  }, []);

  const handleStartGuidedCase = (taskType: CaseState['task_type']) => {
    if (!caseReady) {
      toast.info('Chức năng này chưa sẵn sàng. Bạn vẫn có thể dùng tra cứu quy định.');
      return;
    }
    setGuidedTask(taskType);
    setGuidedDraft(null);
    setComposerDraft({ text: '', intent: taskType === 'build_compliance_checklist' ? 'compliance_checklist' : 'case_assessment', interactionSource: 'guided_form' });
  };

  const submitGuidedCase = async (
    facts: Record<string, string>,
    confirmationStatuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>,
    taskType: CaseState['task_type'],
  ) => {
    if (!caseReady) throw new Error('Chức năng xử lý trường hợp hiện chưa sẵn sàng.');
    let sessionId = activeSessionId;
    if (!sessionId) {
      sessionId = crypto.randomUUID();
      pendingLocalSessionId = sessionId;
      useChatStore.getState().setActiveSession(sessionId);
      navigate(`/conversations/${sessionId}`);
    }
    const completed = await sendMessage(
      'Hãy kiểm tra trường hợp của doanh nghiệp dựa trên thông tin tôi đã cung cấp.',
      sessionId,
      'auto',
      {
        operation: activeCase ? 'continue_case' : 'message',
        intentHint: taskType === 'build_compliance_checklist' ? 'compliance_checklist' : 'case_assessment',
        interactionSource: 'guided_form',
        factUpdates: Object.fromEntries(Object.entries(facts).map(([key, value]) => [key, {
          value,
          confirmation_status: confirmationStatuses[key] || 'user_confirmed',
        }])),
      },
    );
    if (!completed) {
      throw new Error('Câu trả lời bị gián đoạn. Bạn có thể giữ nguyên thông tin và thử lại.');
    }
    setGuidedTask(null);
    setGuidedDraft(null);
    setCaseDrawerOpen(false);
    setCaseDirty(false);
  };

  const handleContinueCase = (
    facts: Record<string, string>,
    confirmationStatuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'> = {},
    taskType: CaseState['task_type'] = 'assess_epr_obligation',
  ) => {
    if (!activeSessionId || !caseReady) return;
    const prompt = activeCase?.last_query || 'Tiếp tục đánh giá tình huống này.';
    void sendMessage(prompt, activeSessionId, 'auto', {
      operation: 'continue_case',
      intentHint: taskType === 'build_compliance_checklist' ? 'compliance_checklist' : 'case_assessment',
      interactionSource: 'case_panel',
      casePatch: facts,
      factUpdates: Object.fromEntries(Object.entries(facts).map(([key, value]) => [key, {
        value,
        confirmation_status: confirmationStatuses[key] || 'user_confirmed',
      }])),
      onAccepted: () => {
        setCaseDirty(false);
        setCaseDrawerOpen(false);
      },
    });
  };

  const closeCaseDrawer = useCallback((): boolean => {
    if (caseDirty && !window.confirm('Bỏ các thay đổi chưa lưu?')) return false;
    setCaseDirty(false);
    setCaseDrawerOpen(false);
    return true;
  }, [caseDirty]);

  const handleNewSession = () => {
    setOpenSources(null);
    if (!closeCaseDrawer()) return;
    navigate('/');
  };

  const handleRegenerate = () => {
    if (activeSessionId && legalReady) void regenerateResponse(activeSessionId);
  };

  const handleResearch = (query: string) => {
    if (!activeSessionId || !query.trim()) return;
    if (!webReady) {
      toast.info('Tìm nguồn chính thức bên ngoài kho văn bản hiện chưa khả dụng.');
      return;
    }
    void sendMessage(query, activeSessionId, 'research_web', { operation: 'message' });
  };

  const handleOpenSources = (
    documents: SourceDocument[],
    citations: Array<Record<string, unknown>>,
    focusIndex?: number,
    answerPreview?: boolean,
  ) => {
    if (documents.length || citations.length) {
      setOpenSources({ documents, citations, focusIndex, preview: answerPreview ?? preview });
    }
  };

  useKeyboardShortcuts({ onStop: stopGeneration, isStreaming });

  const sharedSidebarProps = {
    onSelectSession: (sessionId: string) => {
      if (!closeCaseDrawer()) return;
      navigate(`/conversations/${sessionId}`);
    },
    onClearAll: handleNewSession,
    onNewSession: handleNewSession,
  };

  const conversationBody = sessionLoadStatus === 'loading' && Boolean(conversationId) ? (
    <div className="flex min-h-0 flex-1 items-center justify-center p-6" role="status">
      <div className="text-center text-sm text-[#667085]">
        <span className="mx-auto block h-6 w-6 animate-spin rounded-full border-2 border-[#80d5cb] border-t-[#006a63]" />
        <p className="mt-3">Đang tải cuộc trò chuyện…</p>
      </div>
    </div>
  ) : sessionLoadStatus === 'error' && Boolean(conversationId) ? (
    <div className="flex min-h-0 flex-1 items-center justify-center p-6" role="alert">
      <div className="max-w-md rounded-xl border border-[#f0b7b2] bg-[#fff0ef] p-5 text-center text-[#7f1d1d]">
        <Icon className="mx-auto" name="alert" size={24} />
        <p className="mt-3 text-sm font-semibold">Không thể tải cuộc trò chuyện</p>
        <p className="mt-1 text-sm leading-6">{sessionLoadError}</p>
        <button className="mt-4 rounded-md bg-[#ba1a1a] px-3 py-2 text-xs font-semibold text-white" onClick={() => conversationId && void loadConversationFromRoute(conversationId)} type="button">
          Thử lại
        </button>
      </div>
    </div>
  ) : messages.length === 0 && !isStreaming ? (
    <WelcomeScreen
      caseDisabled={!caseReady}
      caseDisabledReason="Chức năng xử lý trường hợp hiện chưa sẵn sàng."
      disabled={!legalReady}
      guidedTask={guidedTask}
      isStreaming={isStreaming}
      onSendPrompt={handleSend}
      onPrefillPrompt={handlePrefill}
      onStop={stopGeneration}
      onStartCase={handleStartGuidedCase}
      onGuidedSubmit={submitGuidedCase}
      onCancelGuided={() => {
        setGuidedTask(null);
        setGuidedDraft(null);
        setComposerDraft({ text: '', intent: 'auto', interactionSource: 'composer' });
      }}
      onGuidedDraftChange={handleGuidedDraftChange}
      draftText={composerDraft.text}
      onDraftChange={(text) => setComposerDraft({ text, interactionSource: 'composer' })}
      intentLabel={intentLabels[composerDraft.intent]}
      onClearIntent={() => setComposerDraft({ intent: 'auto', interactionSource: 'composer' })}
    />
  ) : (
    <>
      <WorkflowTimeline isStreaming={isStreaming} statusMessage={statusMessage} steps={workflowSteps} turnStatus={lastAssistantStatus} />
      <MessageList
        error={error}
        isStreaming={isStreaming}
        messages={messages}
        onContinueCase={caseReady ? submitGuidedCase : undefined}
        onOpenCase={activeCase ? () => setCaseDrawerOpen(true) : undefined}
        onResearch={handleResearch}
        onOpenSources={handleOpenSources}
        onRegenerate={handleRegenerate}
        onRetry={() => void retryLastTurn()}
        statusMessage={statusMessage}
        streamingContent={streamingContent}
      />
      {guidedTask && guidedDraft?.formState && error && !isStreaming && (
        <div className="shrink-0 border-t border-[#d9e1df] bg-[#fcfcfa] px-3 py-3 sm:px-6">
          <div className="mx-auto max-w-[820px]">
            <p className="mb-2 text-xs font-semibold text-[#53615e]">Bạn có thể sửa thông tin rồi thử lại:</p>
            <GuidedCaseCard
              initialCaseState={guidedDraft.formState}
              onDraftChange={handleRecoveryDraftChange}
              onSubmit={submitGuidedCase}
              taskType={guidedDraft.taskType}
            />
          </div>
        </div>
      )}
      <div className="shrink-0 border-t border-[#d9e1df] bg-[#fcfcfa]/95 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-[820px] justify-center">
          <ChatInput
            disabled={!legalReady}
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
  );

  return (
    <div className="flex h-[100dvh] min-h-0 overflow-hidden bg-[#fcfcfa] text-[#181c1c]">
      {(isDesktop || isTablet) && (
        <div className={`flex h-full shrink-0 overflow-hidden transition-[width] duration-200 ease-out ${isTablet || sidebarCollapsed ? 'w-16' : 'w-[264px]'}`}>
          <Sidebar
            {...sharedSidebarProps}
            collapsed={isTablet || sidebarCollapsed}
            onToggle={isTablet ? () => setMobileSidebarOpen(true) : () => setSidebarCollapsed((value) => !value)}
          />
        </div>
      )}

      {mobileSidebarOpen && (
        <div className="fixed inset-0 z-30 lg:hidden">
          <button aria-label="Đóng lịch sử trò chuyện" className="absolute inset-0 h-full w-full bg-slate-950/25 backdrop-blur-[1px]" onClick={() => setMobileSidebarOpen(false)} type="button" />
          <div className="absolute inset-y-0 left-0 w-[min(304px,calc(100vw-48px))] shadow-[12px_0_32px_rgba(24,28,28,0.10)]">
            <Sidebar {...sharedSidebarProps} isMobile onDismiss={() => setMobileSidebarOpen(false)} />
          </div>
        </div>
      )}

      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-[#fcfcfa]">
        <Header
          hasActiveCase={Boolean(activeCase)}
          me={me}
          readiness={headerReadiness}
          onLogout={onLogout}
          onOpenCase={() => setCaseDrawerOpen(true)}
          onOpenMobileNav={() => setMobileSidebarOpen(true)}
        />

        {preview && (
          <div className="flex shrink-0 items-center justify-center gap-2 border-b border-[#d7a65a] bg-[#fff1d7] px-4 py-2 text-center text-xs font-semibold text-[#714b18]" role="status">
            <Icon name="alert" size={15} />
            Chế độ xem trước — câu trả lời có thể thay đổi khi kho văn bản được phê duyệt.
          </div>
        )}
        {!legalReady && !preview && (
          <div className="flex shrink-0 items-center justify-center gap-2 border-b border-[#ead6b8] bg-[#fff8ea] px-4 py-2 text-center text-xs text-[#714b18]" role="status">
            <Icon name="wifiOff" size={15} />
            {readinessMessage(readiness, readinessOffline)}
            <button className="rounded border border-[#d8b77c] px-2 py-1 font-medium hover:bg-[#fff0cf]" onClick={() => void checkHealth()} type="button">Thử lại</button>
          </div>
        )}

        {conversationBody}
      </main>

      <SourceDrawer
        citations={openSources?.citations}
        documents={openSources?.documents || []}
        focusIndex={openSources?.focusIndex}
        isOpen={Boolean(openSources)}
        onClose={() => setOpenSources(null)}
        preview={Boolean(openSources?.preview)}
      />

      <Drawer
        description="Bảng này chỉ xuất hiện khi bạn muốn đánh giá trường hợp hoặc tạo danh sách việc cần làm EPR."
        isOpen={caseDrawerOpen && Boolean(activeCase)}
        onClose={closeCaseDrawer}
        title="Thông tin tình huống"
      >
        <CaseFactsPanel
          caseState={activeCase}
          conversationId={activeSessionId}
          onCaseChange={(caseState) => useChatStore.getState().setActiveCase(caseState)}
          onContinue={handleContinueCase}
          onDirtyChange={setCaseDirty}
        />
      </Drawer>

      <ToastContainer />
    </div>
  );
}

function UnknownRouteRedirect() {
  useEffect(() => {
    toast.info('Đường dẫn không tồn tại. Đã quay về trang bắt đầu.');
  }, []);
  return <Navigate replace to="/" />;
}

export default function App() {
  const [authState, setAuthState] = useState<'ready' | 'loading' | 'signed_out' | 'error'>('loading');
  const [authError, setAuthError] = useState('');
  const initialised = useRef(false);
  const setMe = useAuthStore((state) => state.setMe);

  const initialiseAuth = useCallback(async () => {
    setAuthState('loading');
    setAuthError('');
    try {
      if (isOidcConfigured()) {
        await completeLogin();
        if (!getAuthSession()) {
          setMe(null);
          setAuthState('signed_out');
          return;
        }
      }
      try {
        setMe(await getMe());
      } catch (error) {
        if (isOidcConfigured()) throw error;
        setMe(null);
      }
      setAuthState('ready');
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Không thể xác thực với SSO');
      setAuthState('error');
    }
  }, [setMe]);

  useEffect(() => {
    if (initialised.current) return;
    initialised.current = true;
    void initialiseAuth();
  }, [initialiseAuth]);

  useEffect(() => {
    const expired = () => {
      setMe(null);
      setAuthState('signed_out');
      toast.info('Phiên đăng nhập đã hết hạn. Đăng nhập lại để tiếp tục tại cuộc trò chuyện này.');
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
  }, [setMe]);

  const login = useCallback(async () => {
    setAuthState('loading');
    try {
      await beginLogin();
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Không thể bắt đầu đăng nhập');
      setAuthState('error');
    }
  }, []);

  const logout = useCallback(() => {
    rememberReturnTo();
    clearAuthSession();
    setMe(null);
    setAuthState('signed_out');
  }, [setMe]);

  if (isOidcConfigured() && authState !== 'ready') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#fcfcfa] p-6 text-[#172033]">
        <section className="w-full max-w-md rounded-2xl border border-[#d9e1df] bg-white p-7 shadow-sm">
          <h1 className="text-lg font-semibold">Trợ lý pháp lý EPR</h1>
          <p className="mt-2 text-sm text-[#667085]">
            {authState === 'loading'
              ? 'Đang kiểm tra phiên đăng nhập…'
              : authState === 'signed_out'
                ? 'Đăng nhập bằng tài khoản nội bộ để tiếp tục.'
                : authError}
          </p>
          {authState !== 'loading' && (
            <button className="mt-5 rounded-lg bg-[#0f766e] px-4 py-2 text-sm font-semibold text-white" onClick={() => void login()} type="button">
              Đăng nhập
            </button>
          )}
        </section>
        <ToastContainer />
      </main>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<LegalAssistantWorkspace onLogout={isOidcConfigured() ? logout : undefined} />} />
      <Route path="/conversations/:conversationId" element={<LegalAssistantWorkspace onLogout={isOidcConfigured() ? logout : undefined} />} />
      <Route path="*" element={<UnknownRouteRedirect />} />
    </Routes>
  );
}
