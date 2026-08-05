import { useEffect, useRef, useCallback, useState } from 'react';

interface UseAutoScrollOptions {
  enabled?: boolean;
  offset?: number;
}

/**
 * Hook for auto-scrolling to bottom when content changes
 */
export function useAutoScroll(options: UseAutoScrollOptions = {}) {
  const { enabled = true, offset = 100 } = options;
  const containerRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const shouldAutoScrollRef = useRef(enabled);
  const [isAtBottom, setIsAtBottom] = useState(true);

  /**
   * Check if the container is scrolled to the bottom
   */
  const checkIsAtBottom = useCallback(() => {
    const el = containerRef.current;
    if (!el) return true;

    const { scrollTop, scrollHeight, clientHeight } = el;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    return distanceFromBottom < offset;
  }, [offset]);

  /**
   * Scroll to bottom
   */
  const scrollToBottom = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;

    el.scrollTo({
      top: el.scrollHeight,
      behavior: 'smooth',
    });
  }, []);

  /**
   * Scroll to bottom instantly (no animation)
   */
  const scrollToBottomInstant = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  // Track scroll position to detect if user is at bottom
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handleScroll = () => {
      const atBottom = checkIsAtBottom();
      isAtBottomRef.current = atBottom;
      shouldAutoScrollRef.current = atBottom;
      setIsAtBottom(atBottom);
    };

    handleScroll();
    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => el.removeEventListener('scroll', handleScroll);
  }, [checkIsAtBottom]);

  // Auto-scroll when content changes (assigning scrollTop usually fires `scroll`, updating isAtBottom)
  useEffect(() => {
    if (!shouldAutoScrollRef.current || !enabled) return;
    scrollToBottomInstant();
  });

  return {
    containerRef,
    scrollToBottom,
    isAtBottom,
  };
}
