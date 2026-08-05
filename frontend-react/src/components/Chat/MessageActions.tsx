import { useState } from 'react';
import type { ChatMessage } from '@/types';
import { copyToClipboard } from '@/utils/clipboard';
import { toast } from '@/components/UI/Toast';
import { cn } from '@/lib/cn';

interface MessageActionsProps {
  message: ChatMessage;
  onCopy: () => void;
  copied: boolean;
  onRegenerate?: () => void;
}

/**
 * Message action buttons - copy, regenerate, feedback
 */
export function MessageActions({ message, onCopy, copied, onRegenerate }: MessageActionsProps) {
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null);

  const isAssistant = message.role === 'assistant';

  const handleCopy = async () => {
    const success = await copyToClipboard(message.content);
    if (success) {
      onCopy();
      toast.success('Đã sao chép vào clipboard');
    } else {
      toast.error('Không thể sao chép');
    }
  };

  const handleFeedback = (type: 'up' | 'down') => {
    setFeedback(type);
    toast.info(type === 'up' ? 'Cảm ơn bạn đã đánh giá tích cực!' : 'Cảm ơn bạn đã gửi phản hồi');
    // TODO: Send feedback to backend
  };

  return (
    <div className="flex items-center gap-1">
      {/* Copy button */}
      <button
        onClick={handleCopy}
        className={cn(
          'p-1.5 rounded-lg transition-all duration-200',
          copied
            ? 'text-green-500 bg-green-50 dark:bg-green-900/20'
            : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-300'
        )}
        title={copied ? 'Đã sao chép' : 'Sao chép'}
      >
        {copied ? (
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
            />
          </svg>
        )}
      </button>

      {/* Regenerate button (assistant only) */}
      {isAssistant && onRegenerate && (
        <button
          onClick={onRegenerate}
          className="p-1.5 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-300 transition-all duration-200"
          title="Tạo lại phản hồi"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
          </svg>
        </button>
      )}

      {/* Thumbs up/down (assistant only) */}
      {isAssistant && (
        <>
          <button
            onClick={() => handleFeedback('up')}
            className={cn(
              'p-1.5 rounded-lg transition-all duration-200',
              feedback === 'up'
                ? 'text-green-500 bg-green-50 dark:bg-green-900/20'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-300'
            )}
            title="Phản hồi tích cực"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5"
              />
            </svg>
          </button>
          <button
            onClick={() => handleFeedback('down')}
            className={cn(
              'p-1.5 rounded-lg transition-all duration-200',
              feedback === 'down'
                ? 'text-red-500 bg-red-50 dark:bg-red-900/20'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-300'
            )}
            title="Phản hồi tiêu cực"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10 14H5.236a2 2 0 01-1.789-2.894l3.5-7A2 2 0 018.736 3h4.018c.163 0 .326.02.485.06L17 4m0 0v5m0 0h2a2 2 0 012 2v6a2 2 0 01-2 2h-2.5M10 14h2m-2 0v5"
              />
            </svg>
          </button>
        </>
      )}
    </div>
  );
}
