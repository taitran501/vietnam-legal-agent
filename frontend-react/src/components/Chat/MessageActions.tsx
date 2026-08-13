import type { ChatMessage } from '@/types';
import { copyToClipboard } from '@/utils/clipboard';
import { toast } from '@/state/toastStore';
import { cn } from '@/lib/cn';
import { Icon } from '@/components/UI/Icon';
import { submitFeedback } from '@/api/feedback';
import { useChatStore } from '@/state/chatStore';

interface MessageActionsProps {
  copied: boolean;
  message: ChatMessage;
  onCopy: () => void;
  onRegenerate?: () => void;
}

export function MessageActions({ copied, message, onCopy, onRegenerate }: MessageActionsProps) {
  const sessionId = useChatStore((state) => state.activeSessionId);
  const updateMessage = useChatStore((state) => state.updateMessage);
  const isAssistant = message.role === 'assistant';
  const feedback = message.feedback?.rating === 2 ? 'up' : message.feedback?.rating === 1 ? 'down' : null;
  const feedbackState = message.feedbackState || (message.feedback ? 'saved' : 'idle');
  const canRate = isAssistant && message.status === 'complete' && Boolean(message.serverMessageId);

  const handleCopy = async () => {
    if (await copyToClipboard(message.content)) {
      onCopy();
      toast.success('Đã sao chép');
    } else {
      toast.error('Không thể sao chép');
    }
  };

  const handleFeedback = async (type: 'up' | 'down') => {
    if (feedbackState === 'pending') return;
    if (!sessionId || !message.serverMessageId) {
      toast.error('Chưa có mã tin nhắn đã lưu để ghi nhận phản hồi');
      return;
    }
    const previousFeedback = message.feedback;
    updateMessage(message.id, {
      feedback: { rating: type === 'up' ? 2 : 1 },
      feedbackState: 'pending',
    });
    try {
      await submitFeedback({ session_id: sessionId, message_id: message.serverMessageId, rating: type === 'up' ? 2 : 1 });
      updateMessage(message.id, { feedbackState: 'saved' });
      toast.info(type === 'up' ? 'Đã lưu đánh giá hữu ích.' : 'Đã lưu phản hồi chưa hữu ích.');
    } catch {
      updateMessage(message.id, { feedback: previousFeedback, feedbackState: 'failed' });
      toast.error('Không thể lưu phản hồi. Hãy thử lại.');
    }
  };

  const baseClass =
    'rounded-md p-1.5 text-[#667085] transition-colors hover:bg-[#e7eceb] hover:text-[#172033] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]';

  return (
    <div className="flex items-center gap-0.5">
      <button
        aria-label={copied ? 'Đã sao chép' : 'Sao chép câu trả lời'}
        className={cn(baseClass, copied && 'bg-[#e7eceb] text-[#006a63]')}
        onClick={() => void handleCopy()}
        title={copied ? 'Đã sao chép' : 'Sao chép'}
        type="button"
      >
        <Icon name={copied ? 'check' : 'copy'} size={15} />
      </button>

      {isAssistant && message.status === 'complete' && message.serverMessageId && onRegenerate && (
        <button
          aria-label="Tạo lại câu trả lời"
          className={baseClass}
          onClick={onRegenerate}
          title="Tạo lại"
          type="button"
        >
          <Icon name="history" size={15} />
        </button>
      )}

      {canRate && (
        <>
          <button
            aria-label="Câu trả lời hữu ích"
            className={cn(baseClass, feedback === 'up' && 'bg-[#e7eceb] text-[#006a63]')}
            onClick={() => void handleFeedback('up')}
            title={feedbackState === 'pending' ? 'Đang lưu…' : feedbackState === 'saved' ? 'Đã lưu' : 'Hữu ích'}
            type="button"
          >
            <span aria-hidden="true" className="text-sm leading-none">↑</span>
          </button>
          <button
            aria-label="Câu trả lời chưa hữu ích"
            className={cn(baseClass, feedback === 'down' && 'bg-[#fff0ef] text-[#ba1a1a]')}
            onClick={() => void handleFeedback('down')}
            title={feedbackState === 'pending' ? 'Đang lưu…' : feedbackState === 'failed' ? 'Lưu thất bại — thử lại' : 'Chưa hữu ích'}
            type="button"
          >
            <span aria-hidden="true" className="text-sm leading-none">↓</span>
          </button>
        </>
      )}
    </div>
  );
}
