import { useCallback, useRef } from 'react';
import { streamChat } from '@/utils/sseParser';
import { useChatStore } from '@/state/chatStore';
import { useSessionStore } from '@/state/sessionStore';
import * as sessionsApi from '@/api/sessions';
import { toast } from '@/state/toastStore';
import type { ChatMessage, ResponseSource, SourceDocument, WorkflowMetadata } from '@/types';

const responseSources: ReadonlySet<ResponseSource> = new Set([
  'legal',
  'chitchat',
  'web_search',
  'cache',
  'follow_up',
  'error',
]);

function asResponseSource(value: string | undefined): ResponseSource | undefined {
  return value && responseSources.has(value as ResponseSource) ? (value as ResponseSource) : undefined;
}

function titleFromQuery(query: string, maxLen = 72): string {
  const t = query.trim();
  if (!t) return 'Cuộc trò chuyện mới';
  return t.length <= maxLen ? t : `${t.slice(0, maxLen - 1)}…`;
}

/** Refresh the sidebar after the durable conversation store persists an exchange. */
async function refreshSessionList(): Promise<void> {
  try {
    const list = await sessionsApi.listSessions(50);
    useSessionStore.getState().setSessions(list);
  } catch (e) {
    console.error('refreshSessionList failed:', e);
  }
}

function ensureSessionVisibleInSidebar(sessionId: string, query: string): void {
  const { sessions } = useSessionStore.getState();
  if (sessions.some((s) => s.id === sessionId)) return;
  const now = Date.now() / 1000;
  useSessionStore.getState().addSession({
    id: sessionId,
    title: titleFromQuery(query),
    created_at: now,
    updated_at: now,
    message_count: 0,
  });
}

/**
 * Enhanced hook for streaming chat responses with retry support
 */
export function useChatStream() {
  const abortControllerRef = useRef<AbortController | null>(null);
  const {
    setStreamingContent,
    appendStreamingContent,
    setStatusMessage,
    updateLastAssistantMessage,
    addMessage,
    setStreaming: setStreamingState,
    setError,
    addWorkflowStep,
    setWorkflowSteps,
    setActiveCase,
  } = useChatStore();

  const runAssistantStream = useCallback(
    async (query: string, sessionId: string) => {
      // Abort any existing stream before starting a new one
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        // Small delay to let the abort propagate
        await new Promise(resolve => setTimeout(resolve, 50));
      }

      setStreamingState(true);
      setStreamingContent('');
      setError(null);
      setWorkflowSteps([]);
      abortControllerRef.current = new AbortController();

      try {
        let fullContent = '';
        let source: ResponseSource | undefined;
        let documents: SourceDocument[] = [];
        let workflow: WorkflowMetadata = {};

        for await (const event of streamChat(
          query,
          sessionId,
          abortControllerRef.current.signal
        )) {
          if (event.type === 'status') {
            setStatusMessage(event.message || '');
          } else if (event.type === 'workflow_step') {
            addWorkflowStep({
              step: event.step || 0,
              action: event.action || 'unknown',
              status: event.status || 'completed',
              trace_id: event.trace_id,
            });
          } else if (event.type === 'response_chunk') {
            const chunk = event.chunk || '';
            fullContent += chunk;
            appendStreamingContent(chunk);
          } else if (event.type === 'response_complete') {
            fullContent = event.text || fullContent;
            source = asResponseSource(event.source);
            documents = (event.documents as SourceDocument[]) || [];
            workflow = {
              task_type: event.task_type,
              case_state: event.case_state,
              assessment: event.assessment,
              checklist: event.checklist,
              assumptions: event.assumptions,
              missing_facts: event.missing_facts,
              citations: event.citations,
              evidence_assessment: event.evidence_assessment,
              trace_id: event.trace_id,
              corpus_id: event.corpus_id,
              pipeline_version: event.pipeline_version,
              termination_reason: event.termination_reason,
            };
            if (event.case_state) setActiveCase(event.case_state);
            break;
          } else if (event.type === 'error') {
            throw new Error(event.message || 'Unknown error occurred');
          }
        }

        updateLastAssistantMessage(fullContent, source, documents, workflow);
        await refreshSessionList();
      } catch (error: unknown) {
        if (!(error instanceof Error && error.name === 'AbortError')) {
          const errorMessage = error instanceof Error ? error.message : 'Đã có lỗi xảy ra';
          setError(errorMessage);
          toast.error(`Lỗi: ${errorMessage}`);
          updateLastAssistantMessage(`⚠️ ${errorMessage}`, 'error', []);
        }
      } finally {
        setStreamingState(false);
        setStatusMessage('');
      }
    },
    [
      appendStreamingContent,
      addWorkflowStep,
      setError,
      setActiveCase,
      setStatusMessage,
      setStreamingContent,
      setStreamingState,
      setWorkflowSteps,
      updateLastAssistantMessage,
    ]
  );

  /**
   * Send message and stream response
   */
  const sendMessage = useCallback(
    async (query: string, sessionId: string) => {
      // Prevent double submission: check if already streaming
      const { isStreaming: currentlyStreaming } = useChatStore.getState();
      if (currentlyStreaming) {
        console.warn('[useChatStream] Ignoring send request — already streaming');
        return;
      }

      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: query,
        timestamp: new Date().toISOString(),
      };
      addMessage(userMessage);

      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
      };
      addMessage(assistantMessage);

      ensureSessionVisibleInSidebar(sessionId, query);

      await runAssistantStream(query, sessionId);
    },
    [addMessage, runAssistantStream]
  );

  /**
   * Regenerate the last assistant response
   */
  const regenerateResponse = useCallback(
    async (sessionId: string) => {
      const state = useChatStore.getState();
      const messages = state.messages;

      const lastUserMsg = [...messages].reverse().find((m) => m.role === 'user');
      if (!lastUserMsg) return;

      state.removeLastMessage();

      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
      };
      state.addMessage(assistantMessage);

      await runAssistantStream(lastUserMsg.content, sessionId);
    },
    [runAssistantStream]
  );

  /**
   * Stop current streaming
   */
  const stopGeneration = useCallback(() => {
    abortControllerRef.current?.abort();
    setStreamingState(false);
  }, [setStreamingState]);

  return {
    sendMessage,
    stopGeneration,
    regenerateResponse,
  };
}
