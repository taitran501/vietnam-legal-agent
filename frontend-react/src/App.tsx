import { useState, useEffect } from 'react';
import { ChatInput } from '@/components/Chat/ChatInput';
import { MessageList } from '@/components/Chat/MessageList';
import { WelcomeScreen } from '@/components/Onboarding/WelcomeScreen';
import { Sidebar } from '@/components/Layout/Sidebar';
import { Header } from '@/components/Layout/Header';
import { ToastContainer } from '@/components/UI/Toast';
import { useChatStream } from '@/hooks/useChatStream';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useChatStore } from '@/state/chatStore';
import { cn } from '@/lib/cn';

const FAQ_THRESHOLD = 0.75;

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isHealthy, setIsHealthy] = useState(true);
  const { sendMessage, stopGeneration, regenerateResponse } = useChatStream();
  const {
    messages,
    isStreaming,
    streamingContent,
    statusMessage,
    activeSessionId,
    error,
  } = useChatStore();

  // Check backend health
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
    const interval = setInterval(checkHealth, 30000); // Check every 30s
    return () => clearInterval(interval);
  }, []);

  const handleSend = (query: string) => {
    let sessionId = activeSessionId;
    
    if (!sessionId) {
      // Generate a new session ID if none exists
      sessionId = crypto.randomUUID();
      useChatStore.getState().setActiveSession(sessionId);
    }
    
    sendMessage(query, sessionId, FAQ_THRESHOLD);
  };

  const handleSelectSession = (sessionId: string) => {
    useChatStore.getState().setActiveSession(sessionId);
  };

  const handleRegenerate = () => {
    if (activeSessionId) {
      regenerateResponse(activeSessionId, FAQ_THRESHOLD);
    }
  };

  // Keyboard shortcuts
  useKeyboardShortcuts({
    onSend: () => {
      // This will be handled by the input component
    },
    onStop: stopGeneration,
    isStreaming,
  });

  return (
    <div className="flex h-screen bg-white dark:bg-gray-900 overflow-hidden">
      {/* Sidebar */}
      <div
        className={cn(
          'flex min-h-0 flex-shrink-0 flex-col transition-all duration-300 ease-in-out border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900',
          sidebarOpen ? 'w-72' : 'w-0 overflow-hidden'
        )}
      >
        <Sidebar
          onSelectSession={handleSelectSession}
          onClearAll={() => useChatStore.getState().clearChat()}
        />
      </div>

      {/* Main chat area — min-h-0 lets the message column shrink so inner overflow-y-auto can scroll */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Header */}
        <Header
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
          isHealthy={isHealthy}
        />

        {/* Content area */}
        {messages.length === 0 && !isStreaming ? (
          /* Welcome screen */
          <WelcomeScreen onSendPrompt={handleSend} />
        ) : (
          /* Message list */
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            streamingContent={streamingContent}
            statusMessage={statusMessage}
            error={error}
            onRegenerate={handleRegenerate}
          />
        )}

        {/* Input */}
        <ChatInput
          onSend={handleSend}
          onStop={stopGeneration}
          isStreaming={isStreaming}
          disabled={!activeSessionId && messages.length > 0}
        />
      </div>

      {/* Toast notifications */}
      <ToastContainer />
    </div>
  );
}

export default App;
