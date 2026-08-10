import { useCallback, useEffect, useState } from 'react';
import { cn } from '@/lib/cn';
import { getToasts, removeToast, subscribeToasts, type ToastData } from '@/state/toastStore';

function useToasts() {
  const [items, setItems] = useState(getToasts);
  useEffect(() => subscribeToasts(setItems), []);
  return items;
}

export function ToastContainer() {
  const items = useToasts();
  return (
    <div className="pointer-events-none fixed inset-x-3 top-3 z-[60] flex flex-col items-end gap-2 sm:left-auto sm:right-4 sm:top-4 sm:w-[360px]">
      {items.map((item) => <ToastItem item={item} key={item.id} />)}
    </div>
  );
}

function ToastItem({ item }: { item: ToastData }) {
  const [exiting, setExiting] = useState(false);
  const dismiss = useCallback(() => {
    setExiting(true);
    window.setTimeout(() => removeToast(item.id), 180);
  }, [item.id]);

  useEffect(() => {
    if (!item.duration || item.duration <= 0) return;
    const timer = window.setTimeout(dismiss, item.duration);
    return () => window.clearTimeout(timer);
  }, [dismiss, item.duration]);

  const colors = {
    success: 'border-l-[#1d8b66] text-[#185843]',
    error: 'border-l-[#ba1a1a] text-[#8f2424]',
    info: 'border-l-[#555e74] text-[#3e475b]',
    warning: 'border-l-[#b7791f] text-[#714b18]',
  }[item.type];
  const icons = { success: '✓', error: '!', info: 'i', warning: '!' };

  return (
    <div
      className={cn(
        'pointer-events-auto flex w-full items-start gap-3 rounded-lg border border-[#d9e1df] border-l-4 bg-white px-3.5 py-3 shadow-[0_10px_28px_rgba(24,28,28,0.12)] transition-all duration-200',
        colors,
        exiting ? 'translate-x-4 opacity-0' : 'translate-x-0 opacity-100'
      )}
      role="status"
    >
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-current/10 text-xs font-bold">
        {icons[item.type]}
      </span>
      <p className="min-w-0 flex-1 text-sm font-medium leading-5">{item.message}</p>
      <button
        aria-label="Đóng thông báo"
        className="rounded p-0.5 text-[#84908d] hover:bg-[#f1f4f3] hover:text-[#172033]"
        onClick={dismiss}
        type="button"
      >
        ×
      </button>
    </div>
  );
}
