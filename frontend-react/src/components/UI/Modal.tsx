import { useEffect, useId, useRef } from 'react';
import { cn } from '@/lib/cn';
import { Icon } from './Icon';

interface ModalProps {
  cancelText?: string;
  confirmText?: string;
  isOpen: boolean;
  message: string;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  variant?: 'danger' | 'primary';
}

export function Modal({
  cancelText = 'Hủy',
  confirmText = 'Xác nhận',
  isOpen,
  message,
  onClose,
  onConfirm,
  title,
  variant = 'primary',
}: ModalProps) {
  const titleId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    cancelRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <button
        aria-label="Đóng hộp thoại"
        className="absolute inset-0 h-full w-full cursor-default bg-[#172033]/25 backdrop-blur-[1px] motion-safe:animate-[fadeIn_180ms_ease-out]"
        onClick={onClose}
        type="button"
      />
      <div
        aria-labelledby={titleId}
        aria-modal="true"
        className="relative w-full max-w-sm rounded-xl border border-[#d9e1df] bg-white p-5 shadow-[0_20px_50px_rgba(24,28,28,0.16)] motion-safe:animate-[messageIn_180ms_ease-out]"
        role="dialog"
      >
        <div className="flex items-start gap-3">
          {variant === 'danger' && (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#ffdad6] text-[#ba1a1a]">
              <Icon name="alert" size={19} />
            </span>
          )}
          <div>
            <h3 className="text-base font-semibold leading-6 text-[#172033]" id={titleId}>{title}</h3>
            <p className="mt-1.5 text-sm leading-6 text-[#667085]">{message}</p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2.5">
          <button
            className="rounded-lg border border-[#bdc9c6] bg-white px-4 py-2 text-sm font-semibold text-[#3e4947] transition-colors hover:bg-[#f1f4f3] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]"
            onClick={onClose}
            ref={cancelRef}
            type="button"
          >
            {cancelText}
          </button>
          <button
            className={cn(
              'rounded-lg px-4 py-2 text-sm font-semibold text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2',
              variant === 'danger'
                ? 'bg-[#ba1a1a] hover:bg-[#93000a] focus-visible:ring-[#ba1a1a]'
                : 'bg-[#0f766e] hover:bg-[#005c55] focus-visible:ring-[#0f766e]'
            )}
            onClick={() => {
              onConfirm();
              onClose();
            }}
            type="button"
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
