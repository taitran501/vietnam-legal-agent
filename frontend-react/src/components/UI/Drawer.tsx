import { useEffect, useId, useRef, type ReactNode } from 'react';
import { Icon } from './Icon';

interface DrawerProps {
  children: ReactNode;
  description?: string;
  isOpen: boolean;
  onClose: () => void;
  title: string;
}

export function Drawer({ children, description, isOpen, onClose, title }: DrawerProps) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKeyDown, true);
    return () => document.removeEventListener('keydown', onKeyDown, true);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-40" role="presentation">
      <button
        aria-label="Đóng bảng thông tin"
        className="absolute inset-0 h-full w-full cursor-default bg-slate-950/20 backdrop-blur-[1px] motion-safe:animate-[fadeIn_180ms_ease-out]"
        onClick={onClose}
        type="button"
      />
      <aside
        aria-labelledby={titleId}
        aria-modal="true"
        className="absolute inset-y-0 right-0 flex w-full max-w-[420px] flex-col border-l border-[#d9e1df] bg-[#fcfcfa] shadow-[-12px_0_32px_rgba(24,28,28,0.08)] motion-safe:animate-[drawerIn_220ms_cubic-bezier(0.4,0,0.2,1)]"
        role="dialog"
      >
        <div className="flex min-h-16 items-start justify-between gap-4 border-b border-[#d9e1df] px-5 py-4">
          <div>
            <h2 className="text-[17px] font-semibold text-[#172033]" id={titleId}>
              {title}
            </h2>
            {description && <p className="mt-1 text-xs leading-5 text-[#667085]">{description}</p>}
          </div>
          <button
            ref={closeRef}
            aria-label="Đóng"
            className="-mr-1 rounded-md p-2 text-[#53615e] transition-colors hover:bg-[#e7eceb] hover:text-[#172033] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]"
            onClick={onClose}
            type="button"
          >
            <Icon name="close" size={20} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>
      </aside>
    </div>
  );
}
