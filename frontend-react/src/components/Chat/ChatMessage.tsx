import { useState } from 'react';
import type { ChatMessage } from '@/types';
import { formatTimestamp } from '@/lib/formatters';
import { MarkdownRenderer } from '@/utils/markdown';
import { MessageActions } from './MessageActions';
import { SourceDocuments } from './SourceDocuments';
import { cn } from '@/lib/cn';

interface ChatMessageProps {
  message: ChatMessage;
  onRegenerate?: () => void;
}

/**
 * Redesigned message bubble with markdown rendering and actions
 */
export function ChatMessageComponent({ message, onRegenerate }: ChatMessageProps) {
  const isUser = message.role === 'user';
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  return (
    <div
      className={cn(
        'group py-4 animate-in fade-in slide-in-from-bottom-2 duration-300',
        isUser ? 'bg-white dark:bg-gray-900' : 'bg-gray-50 dark:bg-gray-800/50'
      )}
    >
      <div className="max-w-4xl mx-auto px-4">
        <div className="flex gap-4">
          {/* Avatar */}
          <div
            className={cn(
              'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center shadow-lg',
              isUser
                ? 'bg-gradient-to-br from-blue-500 to-blue-600 text-white'
                : 'bg-gradient-to-br from-green-500 to-emerald-600 text-white'
            )}
          >
            {isUser ? (
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z"
                  clipRule="evenodd"
                />
              </svg>
            ) : (
              <span className="text-base">⚖️</span>
            )}
          </div>

          {/* Message content */}
          <div className="flex-1 min-w-0">
            {/* Sender name */}
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-semibold text-gray-900 dark:text-white">
                {isUser ? 'Bạn' : 'Trợ lý EPR'}
              </span>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {formatTimestamp(message.timestamp)}
              </span>
            </div>

            {/* Message text with markdown */}
            <div
              className={cn(
                'text-[15px] text-gray-900 dark:text-gray-100 leading-relaxed',
                'prose prose-gray dark:prose-invert max-w-none',
                'prose-p:my-1 prose-ul:my-1 prose-ol:my-1',
                'prose-code:text-sm prose-pre:text-sm'
              )}
            >
              {isUser ? (
                <p className="whitespace-pre-wrap break-words">{message.content}</p>
              ) : (
                <MarkdownRenderer content={message.content} />
              )}
            </div>

            {/* Source documents */}
            {message.documents && message.documents.length > 0 && (
              <SourceDocuments documents={message.documents} />
            )}

            {/* Metadata and actions */}
            <div className="mt-2 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                {message.source && message.source !== 'error' && (
                  <span className="px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded-full capitalize">
                    {message.source}
                  </span>
                )}
                {message.documents && message.documents.length > 0 && (
                  <span>{message.documents.length} tài liệu tham khảo</span>
                )}
              </div>

              {/* Message actions - visible on hover */}
              <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                <MessageActions
                  message={message}
                  onCopy={handleCopy}
                  copied={copied}
                  onRegenerate={onRegenerate}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
