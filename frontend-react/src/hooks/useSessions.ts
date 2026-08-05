import { useCallback, useEffect, useState } from 'react';
import { useSessionStore } from '@/state/sessionStore';
import { useChatStore } from '@/state/chatStore';
import * as sessionsApi from '@/api/sessions';
import { toast } from '@/components/UI/Toast';
import type { ChatMessage } from '@/types';

/**
 * Enhanced hook for session management with full CRUD
 */
export function useSessions() {
  const {
    sessions,
    isLoadingSessions,
    setSessions,
    removeSession,
    updateSession,
    setLoading,
  } = useSessionStore();

  const { setActiveSession, setMessages, clearChat } = useChatStore();
  const [searchQuery, setSearchQuery] = useState('');

  /**
   * Load session list
   */
  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const apiList = await sessionsApi.listSessions(50);
      const activeId = useChatStore.getState().activeSessionId;
      const prev = useSessionStore.getState().sessions;
      const apiIds = new Set(apiList.map((s) => s.id));
      // Keep a local row for the active session until Redis lists it (first message in flight).
      const pendingLocal =
        activeId && !apiIds.has(activeId)
          ? prev.filter((s) => s.id === activeId)
          : [];
      const pendingIds = new Set(pendingLocal.map((s) => s.id));
      const fromApi = apiList.filter((s) => !pendingIds.has(s.id));
      setSessions([...pendingLocal, ...fromApi]);
    } catch (error) {
      console.error('Failed to load sessions:', error);
      toast.error('Không thể tải danh sách cuộc trò chuyện');
    } finally {
      setLoading(false);
    }
  }, [setLoading, setSessions]);

  /**
   * Load session details
   */
  const loadSession = useCallback(
    async (sessionId: string) => {
      try {
        const detail = await sessionsApi.getSession(sessionId);

        // Set active session
        setActiveSession(sessionId);

        // Convert messages to ChatMessage format
        const messages: ChatMessage[] = detail.messages.map((msg, idx) => ({
          id: `${msg.role}-${msg.timestamp}-${idx}`,
          role: msg.role as 'user' | 'assistant',
          content: msg.content,
          timestamp: msg.timestamp,
        }));

        setMessages(messages);
      } catch (error) {
        console.error('Failed to load session:', error);
        toast.error('Không thể tải cuộc trò chuyện');
      }
    },
    [setActiveSession, setMessages]
  );

  /**
   * Delete session with confirmation
   */
  const deleteSession = useCallback(
    async (sessionId: string) => {
      try {
        await sessionsApi.deleteSession(sessionId);
        removeSession(sessionId);

        // If deleted session was active, clear chat
        const { activeSessionId } = useChatStore.getState();
        if (activeSessionId === sessionId) {
          clearChat();
        }

        toast.success('Đã xóa cuộc trò chuyện');
      } catch (error) {
        console.error('Failed to delete session:', error);
        toast.error('Không thể xóa cuộc trò chuyện');
      }
    },
    [removeSession, clearChat]
  );

  /**
   * Create new session (reset chat)
   */
  const createNewSession = useCallback(() => {
    clearChat();
    toast.info('Cuộc trò chuyện mới đã được tạo');
  }, [clearChat]);

  /**
   * Rename session
   */
  const renameSession = useCallback(
    async (sessionId: string, newTitle: string) => {
      try {
        await sessionsApi.updateSession(sessionId, newTitle);
        updateSession(sessionId, { title: newTitle });
        toast.success('Đã đổi tên cuộc trò chuyện');
      } catch (error) {
        console.error('Failed to rename session:', error);
        toast.error('Không thể đổi tên cuộc trò chuyện');
      }
    },
    [updateSession]
  );

  /**
   * Clear all conversations
   */
  const clearAllSessions = useCallback(async () => {
    try {
      // Delete all sessions from backend
      await Promise.all(sessions.map(s => sessionsApi.deleteSession(s.id)));
      
      // Clear local state
      setSessions([]);
      clearChat();
      
      toast.success('Đã xóa tất cả cuộc trò chuyện');
    } catch (error) {
      console.error('Failed to clear all sessions:', error);
      toast.error('Không thể xóa tất cả cuộc trò chuyện');
    }
  }, [sessions, setSessions, clearChat]);

  /**
   * Filtered sessions based on search query
   */
  const filteredSessions = sessions.filter((session) =>
    (session.title || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Load sessions on mount
  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  return {
    sessions: filteredSessions,
    allSessions: sessions,
    isLoadingSessions,
    searchQuery,
    setSearchQuery,
    loadSessions,
    loadSession,
    deleteSession,
    createNewSession,
    renameSession,
    clearAllSessions,
  };
}
