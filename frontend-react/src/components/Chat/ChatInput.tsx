import { useState, useRef, useEffect, type KeyboardEvent, type ChangeEvent } from 'react';
import { cn } from '@/lib/cn';

interface ChatInputProps {
  onSend: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

/**
 * Enhanced chat input with auto-resize and keyboard shortcuts
 */
export function ChatInput({ onSend, onStop, isStreaming, disabled = false }: ChatInputProps) {
  const [input, setInput] = useState('');
  const [lastSendTime, setLastSendTime] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // Reset height to calculate new height
    textarea.style.height = 'auto';
    const newHeight = Math.min(textarea.scrollHeight, 200); // Max 200px
    textarea.style.height = `${newHeight}px`;
  }, [input]);

  // Focus input on mount
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleSend = () => {
    if (!input.trim() || isStreaming || disabled) return;

    // Debounce: prevent double submission within 500ms
    const now = Date.now();
    if (now - lastSendTime < 500) return;
    setLastSendTime(now);

    onSend(input.trim());
    setInput('');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter without Shift/Ctrl/Cmd to send
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
  };

  const isDisabled = disabled || isStreaming;

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <div className="max-w-4xl mx-auto">
        <div className="relative flex items-end gap-2 bg-gray-100 dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 focus-within:border-green-500 focus-within:ring-2 focus-within:ring-green-500/20 transition-all duration-200 shadow-sm">
          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Nhập câu hỏi của bạn... (Shift+Enter xuống dòng)"
            className="flex-1 resize-none bg-transparent px-4 py-3.5 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 focus:outline-none max-h-[200px] overflow-y-auto scrollbar-thin text-[15px]"
            rows={1}
            disabled={isDisabled}
          />

          {/* Send/Stop button */}
          <div className="flex-shrink-0 pb-2 pr-2">
            {isStreaming ? (
              <button
                onClick={onStop}
                className="p-2 bg-red-500 text-white rounded-xl hover:bg-red-600 transition-all duration-200 shadow-lg shadow-red-500/20 hover:shadow-red-500/30 active:scale-95"
                title="Dừng tạo (Escape)"
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM8 7a1 1 0 00-1 1v4a1 1 0 001 1h4a1 1 0 001-1V8a1 1 0 00-1-1H8z"
                    clipRule="evenodd"
                  />
                </svg>
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim() || isDisabled}
                className={cn(
                  'p-2 rounded-xl transition-all duration-200 active:scale-95',
                  input.trim() && !isDisabled
                    ? 'bg-gradient-to-r from-green-500 to-emerald-600 text-white shadow-lg shadow-green-500/20 hover:shadow-green-500/30 hover:from-green-600 hover:to-emerald-700'
                    : 'bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-not-allowed'
                )}
                title="Gửi (Enter)"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                  />
                </svg>
              </button>
            )}
          </div>
        </div>

        {/* Helper text */}
        <div className="mt-2 text-center text-xs text-gray-500 dark:text-gray-400">
          <span>Enter để gửi · Shift+Enter xuống dòng · Escape để dừng</span>
        </div>
      </div>
    </div>
  );
}
