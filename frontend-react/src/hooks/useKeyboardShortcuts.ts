import { useEffect, useCallback, useRef } from 'react';

interface UseKeyboardShortcutsOptions {
  onSend?: () => void;
  onStop?: () => void;
  isStreaming?: boolean;
  disabled?: boolean;
}

/**
 * Hook for keyboard shortcuts
 * Ctrl+Enter / Cmd+Enter: Send message
 * Escape: Stop generation
 */
export function useKeyboardShortcuts(options: UseKeyboardShortcutsOptions = {}) {
  const optionsRef = useRef(options);

  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // Ctrl+Enter or Cmd+Enter to send
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      if (optionsRef.current.onSend && !optionsRef.current.disabled && !optionsRef.current.isStreaming) {
        optionsRef.current.onSend();
      }
    }

    // Escape to stop generation
    if (e.key === 'Escape' && optionsRef.current.isStreaming && optionsRef.current.onStop) {
      e.preventDefault();
      optionsRef.current.onStop();
    }
  }, []);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
}
