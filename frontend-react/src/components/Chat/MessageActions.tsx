import { useState } from 'react';
import type { ChatMessage } from '@/types';
import { copyToClipboard } from '@/utils/clipboard';
import { toast } from '@/state/toastStore';
import { cn } from '@/lib/cn';
import { Icon } from '@/components/UI/Icon';

interface MessageActionsProps {
  copied: boolean;
  message: ChatMessage;
  onCopy: () => void;
  onRegenerate?: () => void;
}

export function MessageActions({ copied, message, onCopy, onRegenerate }: MessageActionsProps) {
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null);
  const isAssistant = message.role === 'assistant';

  const handleCopy = async () => {
    if (await copyToClipboard(message.content)) {
      onCopy();
      toast.success('Đã sao chép');
    } else {
      toast.error('Không thể sao chép');
    }
  };

  const handleFeedback = (type: 'up' | 'down') => {
    setFeedback(type);
    toast.info(type === 'up' ? 'Cảm ơn bạn đã đánh giá!' : 'Cảm ơn bạn đã gửi phản hồi');
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

      {isAssistant && onRegenerate && (
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

      {isAssistant && (
        <>
          <button
            aria-label="Câu trả lời hữu ích"
            className={cn(baseClass, feedback === 'up' && 'bg-[#e7eceb] text-[#006a63]')}
            onClick={() => handleFeedback('up')}
            title="Hữu ích"
            type="button"
          >
            <span aria-hidden="true" className="text-sm leading-none">↑</span>
          </button>
          <button
            aria-label="Câu trả lời chưa hữu ích"
            className={cn(baseClass, feedback === 'down' && 'bg-[#fff0ef] text-[#ba1a1a]')}
            onClick={() => handleFeedback('down')}
            title="Chưa hữu ích"
            type="button"
          >
            <span aria-hidden="true" className="text-sm leading-none">↓</span>
          </button>
        </>
      )}
    </div>
  );
}
