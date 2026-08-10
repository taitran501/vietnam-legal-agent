import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { cn } from '@/lib/cn';
import { Icon } from '@/components/UI/Icon';

interface ChatInputProps {
  autoFocus?: boolean;
  disabled?: boolean;
  isStreaming: boolean;
  onSend: (message: string) => void;
  onStop: () => void;
  variant?: 'conversation' | 'welcome';
  value?: string;
  intentLabel?: string;
  onValueChange?: (value: string) => void;
  onClearIntent?: () => void;
}

export function ChatInput({
  autoFocus = true,
  disabled = false,
  isStreaming,
  onSend,
  onStop,
  variant = 'conversation',
  value,
  intentLabel,
  onValueChange,
  onClearIntent,
}: ChatInputProps) {
  const [localInput, setLocalInput] = useState('');
  const input = value ?? localInput;
  const setInput = (next: string) => {
    if (value === undefined) setLocalInput(next);
    onValueChange?.(next);
  };
  const lastSendTime = useRef(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    const minimum = variant === 'welcome' ? 76 : 28;
    textarea.style.height = `${Math.max(minimum, Math.min(textarea.scrollHeight, 180))}px`;
  }, [input, variant]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  const handleSend = () => {
    if (!input.trim() || isStreaming || disabled) return;
    const now = Date.now();
    if (now - lastSendTime.current < 500) return;
    lastSendTime.current = now;
    onSend(input.trim());
    setInput('');
    onClearIntent?.();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const isDisabled = disabled || isStreaming;

  return (
    <div className={cn('w-full', variant === 'welcome' ? 'max-w-[760px]' : 'max-w-[820px]')}>
      {intentLabel && (
        <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-[#e7f4f1] px-2.5 py-1 text-xs font-semibold text-[#006a63]">
          {intentLabel}
          <button aria-label="Xóa tác vụ đã chọn" className="rounded p-0.5 hover:bg-[#cce9e4]" onClick={onClearIntent} type="button">×</button>
        </div>
      )}
      <div
        className={cn(
          'relative flex items-end border border-[#bdc9c6] bg-white transition-[border-color,box-shadow] duration-200 focus-within:border-[#0f766e] focus-within:ring-2 focus-within:ring-[#0f766e]/15',
          variant === 'welcome' ? 'rounded-xl px-4 pb-3 pt-4' : 'rounded-xl px-3 py-2.5',
          disabled && 'bg-[#f1f4f3] opacity-75'
        )}
      >
        <textarea
          aria-label="Câu hỏi pháp lý"
          className={cn(
            'scrollbar-thin min-h-7 max-h-[180px] flex-1 resize-none overflow-y-auto bg-transparent text-[15px] leading-6 text-[#172033] outline-none placeholder:text-[#84908d] disabled:cursor-not-allowed',
            variant === 'welcome' ? 'pr-14 text-base' : 'px-1 pr-12'
          )}
          disabled={isDisabled}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={variant === 'welcome' ? 'Nhập câu hỏi hoặc mô tả tình huống pháp lý…' : 'Hỏi thêm về nội dung này…'}
          ref={textareaRef}
          rows={1}
          value={input}
        />

        <div className={cn('absolute right-3', variant === 'welcome' ? 'bottom-3' : 'bottom-2.5')}>
          {isStreaming ? (
            <button
              aria-label="Dừng tạo câu trả lời"
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#e6b9b5] bg-[#fff0ef] text-[#ba1a1a] transition-colors hover:bg-[#ffdad6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ba1a1a]"
              onClick={onStop}
              title="Dừng tạo"
              type="button"
            >
              <Icon name="stop" size={18} />
            </button>
          ) : (
            <button
              aria-label="Gửi câu hỏi"
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#0f766e] text-white transition-colors hover:bg-[#005c55] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-[#d7dbd9] disabled:text-[#7a8582]"
              disabled={!input.trim() || isDisabled}
              onClick={handleSend}
              title="Gửi (Enter)"
              type="button"
            >
              <Icon name="send" size={18} />
            </button>
          )}
        </div>
      </div>
      {variant === 'conversation' && (
        <p className="mt-2 px-2 text-center text-[11px] leading-4 text-[#667085]">
          Trợ lý có thể mắc sai sót. Hãy đối chiếu nguồn trước khi sử dụng thông tin quan trọng.
        </p>
      )}
    </div>
  );
}
