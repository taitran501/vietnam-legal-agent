import { useEffect, useState } from 'react';
import { Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ChatInput } from '@/components/Chat/ChatInput';
import { MessageList } from '@/components/Chat/MessageList';
import { WelcomeScreen } from '@/components/Onboarding/WelcomeScreen';
import { Sidebar } from '@/components/Layout/Sidebar';
import { Header } from '@/components/Layout/Header';
import { ToastContainer } from '@/components/UI/Toast';
import { WorkflowTimeline } from '@/components/Agent/WorkflowTimeline';
import { CaseFactsPanel } from '@/components/Case/CaseFactsPanel';
import { useChatStream } from '@/hooks/useChatStream';
import { useSessions } from '@/hooks/useSessions';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useChatStore } from '@/state/chatStore';
import { cn } from '@/lib/cn';

const FAQ_THRESHOLD = 0.75;

function ComplianceWorkspace() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isHealthy, setIsHealthy] = useState(true);
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
  } = useChatStore();

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
        const response = await fetch(`${baseUrl}/api/v1/health`);
        setIsHealthy(response.ok);
      } catch {
        setIsHealthy(false);
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (conversationId && conversationId !== activeSessionId) {
      void loadSession(conversationId);
    }
  }, [activeSessionId, conversationId, loadSession]);

  const handleSend = (query: string) => {
    let sessionId = activeSessionId;
    if (!sessionId) {
      sessionId = crypto.randomUUID();
      useChatStore.getState().setActiveSession(sessionId);
      navigate(`/conversations/${sessionId}`);
    }
    void sendMessage(query, sessionId, FAQ_THRESHOLD);
  };

  const handleSelectSession = (sessionId: string) => navigate(`/conversations/${sessionId}`);
  const handleRegenerate = () => {
    if (activeSessionId) void regenerateResponse(activeSessionId, FAQ_THRESHOLD);
  };

  useKeyboardShortcuts({ onSend: () => undefined, onStop: stopGeneration, isStreaming });

  return (
    <div className="flex h-screen overflow-hidden bg-slate-100 text-slate-950">
      <div
        className={cn(
          'flex min-h-0 flex-shrink-0 flex-col border-r border-slate-200 bg-white transition-all duration-300',
          sidebarOpen ? 'w-72' : 'w-0 overflow-hidden'
        )}
      >
        <Sidebar
          onSelectSession={handleSelectSession}
          onClearAll={() => navigate('/')}
          onNewSession={() => navigate('/')}
        />
      </div>

      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-white">
        <Header sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(!sidebarOpen)} isHealthy={isHealthy} />
        <WorkflowTimeline steps={workflowSteps} isStreaming={isStreaming} />
        {messages.length === 0 && !isStreaming ? (
          <WelcomeScreen onSendPrompt={handleSend} />
        ) : (
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            streamingContent={streamingContent}
            statusMessage={statusMessage}
            error={error}
            onRegenerate={handleRegenerate}
          />
        )}
        <div className="max-h-[320px] overflow-y-auto border-t border-slate-200 lg:hidden">
          <CaseFactsPanel
            conversationId={activeSessionId}
            caseState={activeCase}
            onCaseChange={(caseState) => useChatStore.getState().setActiveCase(caseState)}
          />
        </div>
        <ChatInput onSend={handleSend} onStop={stopGeneration} isStreaming={isStreaming} />
      </main>

      <div className="hidden w-80 min-h-0 shrink-0 lg:block">
        <CaseFactsPanel
          conversationId={activeSessionId}
          caseState={activeCase}
          onCaseChange={(caseState) => useChatStore.getState().setActiveCase(caseState)}
        />
      </div>
      <ToastContainer />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ComplianceWorkspace />} />
      <Route path="/conversations/:conversationId" element={<ComplianceWorkspace />} />
      <Route path="*" element={<ComplianceWorkspace />} />
    </Routes>
  );
}
