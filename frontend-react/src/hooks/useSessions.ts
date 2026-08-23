import { useCallback, useEffect } from 'react';
import axios from 'axios';
import { useSessionStore } from '@/state/sessionStore';
import { useChatStore } from '@/state/chatStore';
import * as sessionsApi from '@/api/sessions';
import { toast } from '@/state/toastStore';
import type { ChatMessage, SourceSnapshot } from '@/types';
import { sourceDocumentsFromSnapshots } from '@/lib/sourceProvenance';

const PAGE_SIZE = 30;
let listController: AbortController | null = null;
let detailController: AbortController | null = null;
let listSequence = 0;
let detailSequence = 0;

function isCancelled(error: unknown): boolean {
  return axios.isCancel(error) || (error instanceof DOMException && error.name === 'AbortError');
}

function isNotFound(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 404;
}

function sourceDocuments(metadata: Record<string, unknown> | undefined) {
  const sources = Array.isArray(metadata?.sources) ? metadata.sources : [];
  return sourceDocumentsFromSnapshots(sources as SourceSnapshot[]);
}

export function useSessions({ autoLoad = true }: { autoLoad?: boolean } = {}) {
  const sessionState = useSessionStore();
  const {
    sessions,
    isLoadingSessions,
    hasLoadedSessions,
    sessionsError,
    hasMoreSessions,
    searchQuery,
    setSessions,
    addSession,
    appendSessions,
    removeSession,
    updateSession,
    setLoading,
    setLoaded,
    setError: setSessionsError,
    setHasMore,
    setSearchQuery,
  } = sessionState;
  const { beginSessionLoad, finishSessionLoad, failSessionLoad, clearChat } = useChatStore();

  const loadSessions = useCallback(async ({ reset = true }: { reset?: boolean } = {}) => {
    const current = useSessionStore.getState();
    if (!reset && (current.isLoadingSessions || !current.hasMoreSessions)) return;
    listController?.abort();
    const controller = new AbortController();
    listController = controller;
    const sequence = ++listSequence;
    const offset = reset ? 0 : current.sessions.length;
    setLoading(true);
    setSessionsError(null);
    try {
      const page = await sessionsApi.listSessions(
        PAGE_SIZE,
        offset,
        current.searchQuery.trim(),
        controller.signal,
      );
      if (sequence !== listSequence) return;
      const latestState = useSessionStore.getState();
      const activeSessionId = useChatStore.getState().activeSessionId;
      const optimisticActiveSession = reset && !latestState.searchQuery.trim() && activeSessionId
        ? latestState.sessions.find((session) => session.id === activeSessionId)
        : undefined;
      const nextPage = optimisticActiveSession && !page.some((session) => session.id === optimisticActiveSession.id)
        ? [optimisticActiveSession, ...page]
        : page;
      if (reset) setSessions(nextPage);
      else appendSessions(page);
      setHasMore(page.length === PAGE_SIZE);
      setLoaded(true);
    } catch (error) {
      if (isCancelled(error) || sequence !== listSequence) return;
      console.error('Failed to load sessions:', error);
      setSessionsError('Không thể tải lịch sử trò chuyện.');
    } finally {
      if (sequence === listSequence) setLoading(false);
    }
  }, [appendSessions, setHasMore, setLoaded, setLoading, setSessions, setSessionsError]);

  const loadMoreSessions = useCallback(async () => {
    await loadSessions({ reset: false });
  }, [loadSessions]);

  const cancelSessionLoad = useCallback(() => {
    detailSequence += 1;
    detailController?.abort();
    detailController = null;
  }, []);

  const loadSession = useCallback(async (sessionId: string): Promise<'loaded' | 'not_found' | 'error' | 'stale'> => {
    cancelSessionLoad();
    const controller = new AbortController();
    detailController = controller;
    const sequence = ++detailSequence;
    beginSessionLoad(sessionId);
    try {
      const [detail, caseState] = await Promise.all([
        sessionsApi.getSession(sessionId, controller.signal),
        sessionsApi.getCaseState(sessionId, controller.signal),
      ]);
      if (sequence !== detailSequence || useChatStore.getState().activeSessionId !== sessionId) return 'stale';
      const existingSession = useSessionStore.getState().sessions.some((session) => session.id === sessionId);
      const sessionInfo = {
        id: sessionId,
        title: detail.title || 'Cuộc trò chuyện mới',
        created_at: detail.created_at,
        updated_at: detail.updated_at,
        message_count: detail.message_count,
      };
      if (existingSession) updateSession(sessionId, sessionInfo);
      else addSession(sessionInfo);
      const messages: ChatMessage[] = detail.messages
        .filter((message) => message.status !== 'superseded')
        .map((message, index) => ({
        id: message.id ? `${message.role}-${message.id}` : `${message.role}-${message.timestamp}-${index}`,
        serverMessageId: message.id,
        role: message.role as 'user' | 'assistant',
        content: message.content,
        timestamp: message.timestamp,
        turnId: message.turn_id || undefined,
        status: message.status || 'complete',
        feedback: message.metadata?.feedback,
        feedbackState: message.metadata?.feedback ? 'saved' : 'idle',
        documents: sourceDocuments(message.metadata as Record<string, unknown> | undefined),
        workflow: (message.metadata || undefined) as ChatMessage['workflow'],
        }));
      finishSessionLoad(sessionId, messages, caseState);
      return 'loaded';
    } catch (error) {
      if (isCancelled(error) || sequence !== detailSequence) return 'stale';
      if (isNotFound(error)) return 'not_found';
      console.error('Failed to load session:', error);
      failSessionLoad('Không thể tải cuộc trò chuyện. Kiểm tra kết nối rồi thử lại.');
      return 'error';
    }
  }, [addSession, beginSessionLoad, cancelSessionLoad, failSessionLoad, finishSessionLoad, updateSession]);

  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      await sessionsApi.deleteSession(sessionId);
      removeSession(sessionId);
      if (useChatStore.getState().activeSessionId === sessionId) clearChat();
      toast.success('Đã xóa cuộc trò chuyện');
    } catch (error) {
      console.error('Failed to delete session:', error);
      toast.error('Không thể xóa cuộc trò chuyện');
    }
  }, [clearChat, removeSession]);

  const createNewSession = useCallback(() => {
    cancelSessionLoad();
    clearChat();
  }, [cancelSessionLoad, clearChat]);

  const renameSession = useCallback(async (sessionId: string, newTitle: string) => {
    try {
      await sessionsApi.updateSession(sessionId, newTitle);
      updateSession(sessionId, { title: newTitle });
      toast.success('Đã đổi tên cuộc trò chuyện');
    } catch (error) {
      console.error('Failed to rename session:', error);
      toast.error('Không thể đổi tên cuộc trò chuyện');
    }
  }, [updateSession]);

  const clearAllSessions = useCallback(async () => {
    try {
      await Promise.all(useSessionStore.getState().sessions.map((session) => sessionsApi.deleteSession(session.id)));
      setSessions([]);
      clearChat();
      toast.success('Đã xóa tất cả cuộc trò chuyện');
    } catch (error) {
      console.error('Failed to clear all sessions:', error);
      toast.error('Không thể xóa tất cả cuộc trò chuyện');
    }
  }, [clearChat, setSessions]);

  useEffect(() => {
    if (!autoLoad) return;
    const timer = window.setTimeout(() => void loadSessions({ reset: true }), searchQuery ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [autoLoad, loadSessions, searchQuery]);

  return {
    sessions,
    isLoadingSessions,
    hasLoadedSessions,
    sessionsError,
    hasMoreSessions,
    searchQuery,
    setSearchQuery,
    loadSessions,
    loadMoreSessions,
    loadSession,
    cancelSessionLoad,
    deleteSession,
    createNewSession,
    renameSession,
    clearAllSessions,
  };
}
