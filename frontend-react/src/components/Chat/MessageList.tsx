import type { ChatMessage, SourceDocument } from '@/types';
import { ChatMessageComponent } from './ChatMessage';
import { TypingIndicator } from './TypingIndicator';
import { useAutoScroll } from '@/hooks/useAutoScroll';
import { Icon } from '@/components/UI/Icon';

interface MessageListProps {
  error: string | null;
  isStreaming: boolean;
  messages: ChatMessage[];
  onOpenCase?: () => void;
  onResearch?: (query: string) => void;
  onOpenSources: (documents: SourceDocument[], citations: Array<Record<string, unknown>>) => void;
  onRegenerate?: () => void;
  statusMessage?: string;
  streamingContent: string;
}

export function MessageList({
  error,
  isStreaming,
  messages,
  onOpenCase,
  onResearch,
  onOpenSources,
  onRegenerate,
  statusMessage,
  streamingContent,
}: MessageListProps) {
  const { containerRef, scrollToBottom, isAtBottom } = useAutoScroll({ enabled: true });
  const last = messages[messages.length - 1];
  const hidePendingAssistant = isStreaming && last?.role === 'assistant' && (last.content?.trim() ?? '') === '';
  const visibleMessages = hidePendingAssistant ? messages.slice(0, -1) : messages;
  const showStreamingRow =
    isStreaming && Boolean(streamingContent) && (last?.role !== 'assistant' || (last.content?.trim() ?? '') === '');

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
              onResearch={message.role === 'assistant' && message.workflow?.available_actions?.includes('research_web')
                ? () => onResearch?.(messages[index - 1]?.content || '')
                : undefined}
              onOpenSources={onOpenSources}
              onRegenerate={
                message.role === 'assistant' && index === visibleMessages.length - 1 && !hidePendingAssistant
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
                <div data-testid="streaming-answer" className="ml-0 mt-3 whitespace-pre-wrap break-words text-[15px] leading-7 text-[#262d2c] typing-cursor sm:ml-[42px] sm:text-base">
                  {streamingContent}
                </div>
              </div>
            </article>
          )}

          {isStreaming && !streamingContent && <TypingIndicator message={statusMessage || 'Đang hiểu yêu cầu…'} />}

          {error && (
            <div className="px-4 py-5 sm:px-6">
              <div className="mx-auto flex w-full max-w-[820px] items-start gap-3 rounded-lg border border-[#f0b7b2] bg-[#fff0ef] p-4 text-[#7f1d1d]">
                <Icon className="mt-0.5 shrink-0" name="alert" size={19} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">Đã xảy ra lỗi khi xử lý</p>
                  <p className="mt-1 break-words text-sm leading-6">{error}</p>
                  {onRegenerate && (
                    <button
                      className="mt-3 rounded-md bg-[#ba1a1a] px-3 py-2 text-xs font-semibold text-white hover:bg-[#93000a] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ba1a1a] focus-visible:ring-offset-2"
                      onClick={onRegenerate}
                      type="button"
                    >
                      Thử lại
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
