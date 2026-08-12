import { useCallback, useEffect, useRef, useState } from 'react';
import { useSessionStore } from '@/state/sessionStore';
import { useChatStore } from '@/state/chatStore';
import * as sessionsApi from '@/api/sessions';
import { toast } from '@/state/toastStore';
import type { ChatMessage } from '@/types';

/**
 * Enhanced hook for session management with full CRUD
 */
export function useSessions() {
  const {
    sessions,
    isLoadingSessions,
    hasLoadedSessions,
    setSessions,
    removeSession,
    updateSession,
    setLoading,
    setLoaded,
  } = useSessionStore();

  const { setActiveSession, setMessages, setActiveCase, clearChat } = useChatStore();
  const [searchQuery, setSearchQuery] = useState('');
  const loadRequestId = useRef(0);

  /**
   * Load session list
   */
  const loadSessions = useCallback(async () => {
    const current = useSessionStore.getState();
    if (current.isLoadingSessions || current.hasLoadedSessions) return;
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
      setLoaded(true);
    } catch (error) {
      console.error('Failed to load sessions:', error);
    } finally {
      setLoading(false);
    }
  }, [setLoaded, setLoading, setSessions]);

  /**
   * Load session details
   */
  const loadSession = useCallback(
    async (sessionId: string) => {
      const requestId = ++loadRequestId.current;
      try {
        const detail = await sessionsApi.getSession(sessionId);
        if (requestId !== loadRequestId.current) return;

        // Set active session
        setActiveSession(sessionId);

        // Convert messages to ChatMessage format
        const messages: ChatMessage[] = detail.messages.map((msg, idx) => ({
          id: msg.id ? `${msg.role}-${msg.id}` : `${msg.role}-${msg.timestamp}-${idx}`,
          serverMessageId: msg.id,
          role: msg.role as 'user' | 'assistant',
          content: msg.content,
          timestamp: msg.timestamp,
          feedback: (msg.metadata as { feedback?: ChatMessage['feedback'] } | undefined)?.feedback,
          documents: (msg.metadata?.sources || []).map((source) => ({
            page_content: source.excerpt || '',
            document_id: source.source_id,
            source: 'legal',
            metadata: {
              Source_Title: source.title,
              Document_Number: source.instrument_number,
              legal_anchor: source.anchor,
              Pages: source.page,
              Source_Start: source.offset_start,
              Source_End: source.offset_end,
              Source_URI: source.official_url,
              effective_status: source.effective_status,
              effective_from: source.effective_from,
              effective_to: source.effective_to,
              amendment_relationship: source.amendment_relationship,
              active_source_document_id: source.active_source_document_id,
              active_source_pages: source.active_source_pages,
              amendment_resolution_status: source.amendment_resolution_status,
              amendment_operations: source.amendment_operations,
              current_law_support: source.current_law_support,
              corpus_as_of_date: source.corpus_as_of_date,
            },
          })),
          workflow: (msg.metadata || undefined) as ChatMessage['workflow'],
        }));

        if (requestId !== loadRequestId.current) return;

        setMessages(messages);
        const caseState = await sessionsApi.getCaseState(sessionId);
        if (requestId !== loadRequestId.current) return;
        setActiveCase(caseState);
      } catch (error) {
        console.error('Failed to load session:', error);
        if (requestId === loadRequestId.current) toast.error('Không thể tải cuộc trò chuyện');
      }
    },
    [setActiveCase, setActiveSession, setMessages]
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
    if (!hasLoadedSessions) void loadSessions();
  }, [hasLoadedSessions, loadSessions]);

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
