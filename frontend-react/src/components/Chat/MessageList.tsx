import type { ChatMessage } from '@/types';
import { ChatMessageComponent } from './ChatMessage';
import { TypingIndicator } from './TypingIndicator';
import { useAutoScroll } from '@/hooks/useAutoScroll';

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  streamingContent: string;
  statusMessage?: string;
  error: string | null;
  onRegenerate?: () => void;
}

/**
 * Scrollable message list with auto-scroll and scroll-to-bottom button
 */
export function MessageList({
  messages,
  isStreaming,
  streamingContent,
  statusMessage,
  error,
  onRegenerate,
}: MessageListProps) {
  const { containerRef, scrollToBottom, isAtBottom } = useAutoScroll({ enabled: true });

  // While streaming, the store holds an empty assistant placeholder; TypingIndicator / streaming
  // row below already represent "Trợ lý EPR". Rendering both caused duplicate headers (bug).
  // SAFETY: Also hide if streamingContent is empty but last message already has content
  // (prevents rendering both the populated message AND a stale streaming row)
  const last = messages[messages.length - 1];
  const hidePendingAssistant =
    isStreaming &&
    last?.role === 'assistant' &&
    (last.content?.trim() ?? '') === '';
  const visibleMessages = hidePendingAssistant ? messages.slice(0, -1) : messages;

  // Only show streaming row if there's actual streaming content AND the last message
  // doesn't already have content (prevents duplicate rendering after response_complete)
  const showStreamingRow =
    isStreaming &&
    streamingContent &&
    (last?.role !== 'assistant' || (last.content?.trim() ?? '') === '');

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* Messages container — flex-1 + min-h-0 required (not h-full) for scroll inside flex column */}
      <div
        ref={containerRef}
        className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain scrollbar-thin"
      >
        <div className="max-w-4xl mx-auto">
          {visibleMessages.map((message, index) => (
            <ChatMessageComponent
              key={`${message.id}-${index}`}
              message={message}
              onRegenerate={
                message.role === 'assistant' &&
                index === visibleMessages.length - 1 &&
                !hidePendingAssistant
                  ? onRegenerate
                  : undefined
              }
            />
          ))}

          {/* Streaming content — only show when actively streaming and last msg is still empty */}
          {showStreamingRow && (
            <div className="py-4 bg-gray-50 dark:bg-gray-800/50 animate-in fade-in duration-300">
              <div className="px-4">
                <div className="flex gap-4">
                  {/* Avatar */}
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center text-white shadow-lg shadow-green-500/20">
                    <span className="text-base">⚖️</span>
                  </div>

                  {/* Streaming text */}
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-semibold text-gray-900 dark:text-white">
                        Trợ lý EPR
                      </span>
                    </div>
                    <div className="text-[15px] text-gray-900 dark:text-gray-100 leading-relaxed whitespace-pre-wrap break-words typing-cursor">
                      {streamingContent}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Typing indicator */}
          {isStreaming && !streamingContent && (
            <TypingIndicator message={statusMessage || 'Đang suy nghĩ...'} />
          )}

          {/* Error message */}
          {error && (
            <div className="py-4 px-4">
              <div className="max-w-4xl mx-auto">
                <div className="flex items-center gap-3 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-red-100 dark:bg-red-900/40 flex items-center justify-center">
                    <svg className="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
                      <path
                        fillRule="evenodd"
                        d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                        clipRule="evenodd"
                      />
                    </svg>
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium text-red-800 dark:text-red-300">
                      Đã xảy ra lỗi
                    </p>
                    <p className="text-sm text-red-600 dark:text-red-400 mt-0.5">
                      {error}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Bottom padding */}
          <div className="h-4" />
        </div>
      </div>

      {/* Scroll to bottom button */}
      {!isAtBottom && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 p-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-full shadow-lg hover:shadow-xl transition-all duration-200 animate-in fade-in zoom-in-95"
          title="Cuộn xuống dưới cùng"
        >
          <svg className="w-5 h-5 text-gray-600 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 14l-7 7m0 0l-7-7m7 7V3"
            />
          </svg>
        </button>
      )}
    </div>
  );
}
