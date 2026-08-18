import { useEffect, useState } from 'react';
import type { CaseState, ChatMessage, SourceDocument, StreamError, WorkflowStep } from '@/types';
import { ChatMessageComponent } from './ChatMessage';
import { TypingIndicator } from './TypingIndicator';
import { useAutoScroll } from '@/hooks/useAutoScroll';
import { Icon } from '@/components/UI/Icon';
import { errorPresentation } from '@/lib/userCopy';

interface MessageListProps {
  error: StreamError | null;
  isStreaming: boolean;
  messages: ChatMessage[];
  onOpenCase?: () => void;
  onContinueCase?: (facts: Record<string, string>, statuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>, taskType: CaseState['task_type']) => Promise<void>;
  onResearch?: (query: string) => void;
  onExport?: (message: ChatMessage) => void;
  onOpenSources: (documents: SourceDocument[], citations: Array<Record<string, unknown>>, focusIndex?: number, preview?: boolean) => void;
  onRegenerate?: () => void;
  onRetry?: () => void;
  statusMessage?: string;
  streamingContent: string;
  webResearchReady: boolean;
  workflowSteps?: WorkflowStep[];
}

export function MessageList({
  error,
  isStreaming,
  messages,
  onOpenCase,
  onContinueCase,
  onResearch,
  onExport,
  onOpenSources,
  onRegenerate,
  onRetry,
  statusMessage,
  streamingContent,
  webResearchReady,
  workflowSteps = [],
}: MessageListProps) {
  const [retryCountdown, setRetryCountdown] = useState(0);
  const { containerRef, scrollToBottom, isAtBottom } = useAutoScroll({ enabled: true });
  const last = messages[messages.length - 1];
  const hidePendingAssistant = isStreaming && last?.role === 'assistant' && (last.content?.trim() ?? '') === '';
  const visibleMessages = (hidePendingAssistant ? messages.slice(0, -1) : messages).filter(
    (message) => message.status !== 'superseded'
      && !(message.role === 'assistant' && message.status === 'failed' && !message.content.trim()),
  );
  const showStreamingRow =
    isStreaming && Boolean(streamingContent) && (last?.role !== 'assistant' || (last.content?.trim() ?? '') === '');
  const displayedError = error ? errorPresentation(error) : null;

  useEffect(() => {
    if (!error?.retryable) {
      setRetryCountdown(0);
      return;
    }
    setRetryCountdown(Math.max(0, Math.ceil(error.retryAfterSeconds || 0)));
  }, [error]);

  useEffect(() => {
    if (retryCountdown <= 0) return;
    const timer = window.setTimeout(() => setRetryCountdown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [retryCountdown]);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-[#fcfcfa]">
      <div
        className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overscroll-y-contain"
        ref={containerRef}
      >
        <div className="mx-auto w-full">
          {visibleMessages.map((message, index) => (
            <ChatMessageComponent
              key={`${message.id}-${index}`}
              message={message}
              onOpenCase={onOpenCase}
              onContinueCase={message.role === 'assistant' && index === visibleMessages.length - 1 ? onContinueCase : undefined}
              onResearch={message.role === 'assistant' && webResearchReady && message.workflow?.available_actions?.includes('research_web')
                ? () => onResearch?.(messages[index - 1]?.content || '')
                : undefined}
              onExport={onExport}
              webResearchReady={webResearchReady}
              onOpenSources={onOpenSources}
              onRegenerate={
                message.role === 'assistant' && message.status === 'complete' && index === visibleMessages.length - 1 && !hidePendingAssistant
                  ? onRegenerate
                  : undefined
              }
            />
          ))}

          {showStreamingRow && (
            <article className="px-4 py-5 motion-safe:animate-[messageIn_240ms_ease-out] sm:px-6">
              <div className="mx-auto w-full max-w-[820px]">
                <div className="flex items-center gap-2.5">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#0f766e] text-white">
                    <Icon name="scale" size={17} />
                  </span>
                  <p className="text-sm font-semibold text-[#005c55]">Trợ lý pháp lý</p>
                </div>
                <div className="ml-0 mt-3 sm:ml-[42px]">
                  {workflowSteps.length > 0 && (
                    <div className="mb-3">
                      <TypingIndicator message={statusMessage} steps={workflowSteps} />
                    </div>
                  )}
                  <div data-testid="streaming-answer" className="whitespace-pre-wrap break-words text-[15px] leading-7 text-[#262d2c] typing-cursor sm:text-base">
                    {streamingContent}
                  </div>
                </div>
              </div>
            </article>
          )}

          {isStreaming && !streamingContent && (
            <TypingIndicator message={statusMessage || 'Đang hiểu yêu cầu…'} steps={workflowSteps} />
          )}

          {error && (
            <div className="px-4 py-5 sm:px-6">
              <div className="mx-auto flex w-full max-w-[820px] items-start gap-3 rounded-lg border border-[#f0b7b2] bg-[#fff0ef] p-4 text-[#7f1d1d]">
                <Icon className="mt-0.5 shrink-0" name="alert" size={19} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">{displayedError?.title}</p>
                  <p className="mt-1 break-words text-sm leading-6">{displayedError?.message}</p>
                  {error.traceId && <p className="mt-1 text-xs opacity-75">Mã theo dõi: {error.traceId}</p>}
                  {error.retryable && onRetry && (
                    <button
                      className="mt-3 rounded-md bg-[#ba1a1a] px-3 py-2 text-xs font-semibold text-white hover:bg-[#93000a] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ba1a1a] focus-visible:ring-offset-2"
                      disabled={retryCountdown > 0}
                      onClick={onRetry}
                      type="button"
                    >
                      {retryCountdown > 0 ? `Thử lại sau ${retryCountdown}s` : 'Thử lại'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
          <div className="h-6" />
        </div>
      </div>

      {!isAtBottom && (
        <button
          aria-label="Cuộn xuống câu trả lời mới nhất"
          className="absolute bottom-4 left-1/2 flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-[#d9e1df] bg-white text-[#53615e] shadow-sm transition-colors hover:bg-[#f1f4f3] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]"
          onClick={scrollToBottom}
          title="Cuộn xuống"
          type="button"
        >
          <Icon name="chevronDown" size={18} />
        </button>
      )}
    </div>
  );
}
