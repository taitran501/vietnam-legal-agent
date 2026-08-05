import { useState, useEffect, useCallback } from 'react';
import { cn } from '@/lib/cn';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

interface ToastData {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

// Global toast store
let toasts: ToastData[] = [];
let listeners: Array<(toasts: ToastData[]) => void> = [];

function notify() {
  listeners.forEach((listener) => listener(toasts));
}

/**
 * Add a toast notification
 */
export function toast(type: ToastType, message: string, duration = 3000) {
  const id = Math.random().toString(36).slice(2);
  toasts = [...toasts, { id, type, message, duration }];
  notify();

  if (duration > 0) {
    setTimeout(() => removeToast(id), duration);
  }

  return id;
}

/**
 * Remove a toast by ID
 */
export function removeToast(id: string) {
  toasts = toasts.filter((t) => t.id !== id);
  notify();
}

/**
 * Hook to subscribe to toasts
 */
export function useToasts() {
  const [currentToasts, setCurrentToasts] = useState(toasts);

  useEffect(() => {
    listeners.push(setCurrentToasts);
    return () => {
      listeners = listeners.filter((l) => l !== setCurrentToasts);
    };
  }, []);

  return currentToasts;
}

/**
 * Toast notification component
 */
export function ToastContainer() {
  const currentToasts = useToasts();

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      {currentToasts.map((t) => (
        <ToastItem key={t.id} toast={t} onRemove={() => removeToast(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onRemove }: { toast: ToastData; onRemove: () => void }) {
  const [isExiting, setIsExiting] = useState(false);

  const handleRemove = useCallback(() => {
    setIsExiting(true);
    setTimeout(onRemove, 200);
  }, [onRemove]);

  useEffect(() => {
    if (toast.duration && toast.duration > 0) {
      const timer = setTimeout(handleRemove, toast.duration);
      return () => clearTimeout(timer);
    }
  }, [toast.duration, handleRemove]);

  const bgColor = {
    success: 'bg-green-500',
    error: 'bg-red-500',
    info: 'bg-blue-500',
    warning: 'bg-yellow-500',
  }[toast.type];

  const icon = {
    success: '✓',
    error: '✕',
    info: 'ℹ',
    warning: '⚠',
  }[toast.type];

  return (
    <div
      className={cn(
        'pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg text-white min-w-[280px] max-w-sm transition-all duration-200',
        bgColor,
        isExiting ? 'opacity-0 translate-x-full' : 'opacity-100 translate-x-0'
      )}
    >
      <span className="flex-shrink-0 w-6 h-6 rounded-full bg-white/20 flex items-center justify-center text-sm font-bold">
        {icon}
      </span>
      <p className="flex-1 text-sm font-medium">{toast.message}</p>
      <button
        onClick={handleRemove}
        className="flex-shrink-0 w-6 h-6 rounded-full bg-white/20 flex items-center justify-center hover:bg-white/30 transition-colors"
      >
        ×
      </button>
    </div>
  );
}

/**
 * Convenience toast functions
 */
toast.success = (message: string, duration?: number) => toast('success', message, duration);
toast.error = (message: string, duration?: number) => toast('error', message, duration);
toast.info = (message: string, duration?: number) => toast('info', message, duration);
toast.warning = (message: string, duration?: number) => toast('warning', message, duration);
