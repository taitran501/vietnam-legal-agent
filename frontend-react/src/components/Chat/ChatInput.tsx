import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { cn } from '@/lib/cn';
import { Icon } from '@/components/UI/Icon';

interface AttachedFile {
  file: File;
  name: string;
  size: string;
  documentId?: string;
  uploading?: boolean;
}

interface ChatInputProps {
  autoFocus?: boolean;
  disabled?: boolean;
  isStreaming: boolean;
  onSend: (message: string) => void;
  onStop: () => void;
  variant?: 'conversation' | 'welcome';
  value?: string;
  placeholder?: string;
  intentLabel?: string;
  onValueChange?: (value: string) => void;
  onClearIntent?: () => void;
  /** Incremented by quick actions to return focus to the composer. */
  focusRequest?: number;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ChatInput({
  autoFocus = true,
  disabled = false,
  isStreaming,
  onSend,
  onStop,
  variant = 'conversation',
  value,
  placeholder,
  intentLabel,
  onValueChange,
  onClearIntent,
  focusRequest,
}: ChatInputProps) {
  const [localInput, setLocalInput] = useState('');
  const [attachedFile, setAttachedFile] = useState<AttachedFile | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
    if (autoFocus || focusRequest !== undefined) textareaRef.current?.focus();
  }, [autoFocus, focusRequest]);

  const handleFileSelect = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const newAttached: AttachedFile = {
      file,
      name: file.name,
      size: formatFileSize(file.size),
      uploading: true,
    };
    setAttachedFile(newAttached);

    // If composer is empty, suggest a friendly default review prompt
    if (!input.trim()) {
      setInput(`Hãy rà soát hợp đồng và phân tích rủi ro pháp lý cho tệp: ${file.name}`);
    }

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('analyze_redline', 'true');

      const res = await fetch('/api/v1/documents/upload', {
        method: 'POST',
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        setAttachedFile((prev) => (prev ? { ...prev, documentId: data.document?.document_id, uploading: false } : null));
      } else {
        setAttachedFile((prev) => (prev ? { ...prev, uploading: false } : null));
      }
    } catch {
      setAttachedFile((prev) => (prev ? { ...prev, uploading: false } : null));
    }
  };

  const handleRemoveFile = () => {
    setAttachedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleSend = () => {
    const textToSend = input.trim();
    if ((!textToSend && !attachedFile) || isStreaming || disabled) return;
    const now = Date.now();
    if (now - lastSendTime.current < 500) return;
    lastSendTime.current = now;

    let finalPrompt = textToSend;
    if (attachedFile && !finalPrompt.includes(attachedFile.name)) {
      finalPrompt = `${finalPrompt}\n[Tài liệu đính kèm: ${attachedFile.name}]`.trim();
    }

    onSend(finalPrompt || `Hãy rà soát tệp: ${attachedFile?.name}`);
    setInput('');
    setAttachedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
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
      {/* Hidden file input */}
      <input
        accept=".pdf,.docx,.txt,.doc"
        className="hidden"
        onChange={handleFileSelect}
        ref={fileInputRef}
        type="file"
      />

      {/* Badges Bar (Intent label & Attached file) */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {intentLabel && (
          <div className="inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-2.5 py-1 text-xs font-semibold text-teal-800 ring-1 ring-teal-600/20">
            {intentLabel}
            <button aria-label="Xóa tác vụ đã chọn" className="rounded p-0.5 hover:bg-teal-100" onClick={onClearIntent} type="button">×</button>
          </div>
        )}

        {attachedFile && (
          <div className="inline-flex items-center gap-1.5 rounded-xl border border-teal-200 bg-teal-50 px-3 py-1 text-xs font-medium text-teal-900 shadow-sm animate-[fadeIn_150ms_ease-out]">
            <Icon name="fileText" size={13} />
            <span className="max-w-[200px] truncate font-semibold">{attachedFile.name}</span>
            <span className="text-[11px] text-teal-600">({attachedFile.size})</span>
            {attachedFile.uploading ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
            ) : (
              <button
                aria-label="Xóa tệp đính kèm"
                className="ml-0.5 rounded p-0.5 text-teal-700 hover:bg-teal-200 hover:text-teal-900"
                onClick={handleRemoveFile}
                type="button"
              >
                ×
              </button>
            )}
          </div>
        )}
      </div>

      <div
        className={cn(
          'relative flex items-end border border-slate-300 bg-white transition-[border-color,box-shadow] duration-200 focus-within:border-teal-600 focus-within:ring-2 focus-within:ring-teal-600/15',
          variant === 'welcome' ? 'rounded-2xl px-4 pb-3 pt-4 shadow-sm' : 'rounded-2xl px-3.5 py-2.5 shadow-sm',
          disabled && 'bg-slate-50 opacity-75'
        )}
      >
        {/* Paperclip upload button */}
        <button
          aria-label="Đính kèm hợp đồng hoặc tài liệu PDF/Word"
          className="mb-0.5 mr-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={isDisabled}
          onClick={() => fileInputRef.current?.click()}
          title="Đính kèm hợp đồng / tài liệu (PDF, Word, TXT)"
          type="button"
        >
          <Icon name="paperclip" size={18} />
        </button>

        <textarea
          aria-label="Câu hỏi pháp lý"
          className={cn(
            'scrollbar-thin min-h-7 max-h-[180px] flex-1 resize-none overflow-y-auto bg-transparent text-[15px] leading-6 text-slate-900 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed',
            variant === 'welcome' ? 'pr-12 text-base' : 'px-1 pr-12'
          )}
          disabled={isDisabled}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder ?? (variant === 'welcome' ? 'Nhập câu hỏi, tình huống, hoặc bấm 📎 đính kèm hợp đồng để rà soát…' : 'Hỏi thêm hoặc đính kèm tài liệu…')}
          ref={textareaRef}
          rows={1}
          value={input}
        />

        <div className={cn('absolute right-3', variant === 'welcome' ? 'bottom-3' : 'bottom-2.5')}>
          {isStreaming ? (
            <button
              aria-label="Dừng tạo câu trả lời"
              className="flex h-8 w-8 items-center justify-center rounded-xl border border-rose-200 bg-rose-50 text-rose-700 transition-colors hover:bg-rose-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-600"
              onClick={onStop}
              title="Dừng tạo"
              type="button"
            >
              <Icon name="stop" size={16} />
            </button>
          ) : (
            <button
              aria-label="Gửi câu hỏi"
              className="flex h-8 w-8 items-center justify-center rounded-xl bg-teal-700 text-white shadow-sm transition-all hover:bg-teal-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
              disabled={(!input.trim() && !attachedFile) || isDisabled}
              onClick={handleSend}
              title="Gửi (Enter)"
              type="button"
            >
              <Icon name="send" size={16} />
            </button>
          )}
        </div>
      </div>

      {variant === 'conversation' && (
        <p className="mt-2 px-2 text-center text-[11px] leading-4 text-slate-400">
          Trợ lý có thể mắc sai sót. Luôn đối chiếu căn cứ pháp luật trước khi áp dụng.
        </p>
      )}
    </div>
  );
}
