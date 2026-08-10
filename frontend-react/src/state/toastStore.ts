export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface ToastData {
  duration?: number;
  id: string;
  message: string;
  type: ToastType;
}

type ToastListener = (items: ToastData[]) => void;
type ToastApi = ((type: ToastType, message: string, duration?: number) => string) & {
  success: (message: string, duration?: number) => string;
  error: (message: string, duration?: number) => string;
  info: (message: string, duration?: number) => string;
  warning: (message: string, duration?: number) => string;
};

let items: ToastData[] = [];
let listeners: ToastListener[] = [];

function notify() {
  listeners.forEach((listener) => listener(items));
}

function addToast(type: ToastType, message: string, duration = 3000) {
  const id = Math.random().toString(36).slice(2);
  items = [...items, { id, type, message, duration }];
  notify();
  return id;
}

export const toast: ToastApi = Object.assign(addToast, {
  success: (message: string, duration?: number) => addToast('success', message, duration),
  error: (message: string, duration?: number) => addToast('error', message, duration),
  info: (message: string, duration?: number) => addToast('info', message, duration),
  warning: (message: string, duration?: number) => addToast('warning', message, duration),
});

export function removeToast(id: string) {
  items = items.filter((item) => item.id !== id);
  notify();
}

export function getToasts(): ToastData[] {
  return items;
}

export function subscribeToasts(listener: ToastListener): () => void {
  listeners = [...listeners, listener];
  return () => {
    listeners = listeners.filter((candidate) => candidate !== listener);
  };
}
