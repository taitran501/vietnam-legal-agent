import { useCallback, useRef } from 'react';
import {
  ChatStreamError,
  streamChat,
  streamErrorFromEvent,
  type StreamTurnOptions,
} from '@/utils/sseParser';
import { useChatStore } from '@/state/chatStore';
import { useSessionStore } from '@/state/sessionStore';
import * as sessionsApi from '@/api/sessions';
import { toast } from '@/state/toastStore';
import type {
  ActiveTurn,
  ChatMessage,
  ResponseSource,
  SourceDocument,
  StreamError,
  TurnOperation,
  WorkflowMetadata,
} from '@/types';

export type TurnOptions = StreamTurnOptions & { onAccepted?: () => void };

interface StoredRun {
  query: string;
  sessionId: string;
  mode: 'auto' | 'research_web';
  options: TurnOptions;
  localAssistantId: string;
}

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
  const text = query.trim();
  if (!text) return 'Cuộc trò chuyện mới';
  return text.length <= maxLen ? text : `${text.slice(0, maxLen - 1)}…`;
}

function waitForNextPaint(): Promise<void> {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

function asStreamError(error: unknown): StreamError {
  if (error instanceof ChatStreamError) {
    return {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      retryAfterSeconds: error.retryAfterSeconds,
      traceId: error.traceId,
      pipelineVersion: error.pipelineVersion,
    };
  }
  return {
    code: 'stream_incomplete',
    message: error instanceof Error ? error.message : 'Luồng trả lời bị gián đoạn.',
    retryable: true,
    retryAfterSeconds: 2,
  };
}

function workflowFromEvent(event: import('@/types').SSEEvent): WorkflowMetadata {
  return {
    task_type: event.task_type,
    route: event.route,
    source_scope: event.source_scope,
    corpus_version: event.corpus_version,
    corpus_sha: event.corpus_sha,
    embedding_profile: event.embedding_profile,
    evidence_status: event.evidence_status,
    available_actions: event.available_actions,
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
    outcome: event.outcome,
    result_type: event.result_type,
    required_issues: event.required_issues,
    covered_issues: event.covered_issues,
    rule_id: event.rule_id,
    rule_pack_version: event.rule_pack_version,
    effective_dates: event.effective_dates,
    corpus_as_of_date: event.corpus_as_of_date,
    sources: event.sources,
    replay_metadata: event.replay_metadata,
    validation_errors: event.validation_errors,
    citation_error: event.citation_error,
    safe_stop_reason: event.safe_stop_reason,
    preview: event.preview,
  };
}

async function refreshSessionList(): Promise<void> {
  try {
    const current = useSessionStore.getState();
    const list = await sessionsApi.listSessions(30, 0, current.searchQuery);
    current.setSessions(list);
    current.setHasMore(list.length === 30);
    current.setLoaded(true);
    current.setError(null);
  } catch (error) {
    console.error('refreshSessionList failed:', error);
  }
}

function ensureSessionVisibleInSidebar(sessionId: string, query: string): void {
  const { sessions } = useSessionStore.getState();
  if (sessions.some((session) => session.id === sessionId)) return;
  const now = Date.now() / 1000;
  useSessionStore.getState().addSession({
    id: sessionId,
    title: titleFromQuery(query),
    created_at: now,
    updated_at: now,
    message_count: 0,
  });
}

function makeAssistant(turnId: string): ChatMessage {
  return {
    id: `assistant-${turnId}`,
    role: 'assistant',
    content: '',
    timestamp: new Date().toISOString(),
    turnId,
    status: 'pending',
  };
}

export function useChatStream() {
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeTurnRef = useRef<ActiveTurn | null>(null);
  const lastFailedRunRef = useRef<StoredRun | null>(null);

  const runAssistantStream = useCallback(async (run: StoredRun) => {
    const store = useChatStore.getState();
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const turnId = run.options.turnId || crypto.randomUUID();
    const operation = run.options.operation || 'message';
    const activeTurn: ActiveTurn = {
      turnId,
      conversationId: run.sessionId,
      localAssistantId: run.localAssistantId,
      operation,
    };
    activeTurnRef.current = activeTurn;
    store.setActiveTurn(activeTurn);
    store.setStreaming(true);
    store.setStreamingContent('');
    store.setStatusMessage('');
    store.setError(null);
    store.setWorkflowSteps([]);
    store.updateMessage(run.localAssistantId, { turnId, status: 'pending' });

    let fullContent = '';
    let terminal = false;
    let accepted = false;
    try {
      for await (const event of streamChat(
        run.query,
        run.sessionId,
        controller.signal,
        run.mode,
        { ...run.options, turnId },
      )) {
        if (event.type === 'status') {
          store.setStatusMessage(event.message || '');
          if (event.stage === 'turn_started') {
            const assistantMessageId = event.assistant_message_id
              ? Number(event.assistant_message_id)
              : undefined;
            const serverTurnId = event.turn_id || turnId;
            const nextTurn = { ...activeTurn, turnId: serverTurnId, assistantMessageId };
            activeTurnRef.current = nextTurn;
            store.setActiveTurn(nextTurn);
            store.updateMessage(run.localAssistantId, {
              serverMessageId: assistantMessageId,
              turnId: serverTurnId,
              status: 'streaming',
            });
            if (!accepted) {
              accepted = true;
              run.options.onAccepted?.();
            }
          }
        } else if (event.type === 'workflow_step') {
          store.addWorkflowStep({
            step: event.step || 0,
            action: event.action || 'unknown',
            label: event.label,
            status: event.status || 'completed',
            trace_id: event.trace_id,
          });
        } else if (event.type === 'response_chunk') {
          const chunk = event.chunk || '';
          fullContent += chunk;
          store.appendStreamingContent(chunk);
          store.updateMessage(run.localAssistantId, { status: 'streaming' });
          await waitForNextPaint();
        } else if (event.type === 'case_update' && event.case_state) {
          store.setActiveCase(event.case_state);
        } else if (event.type === 'input_required' && event.case_state) {
          store.setActiveCase(event.case_state);
        } else if (event.type === 'response_stopped') {
          fullContent = event.text || fullContent;
          const persistedId = event.assistant_message_id
            ? Number(event.assistant_message_id)
            : useChatStore.getState().messages.find((message) => message.id === run.localAssistantId)?.serverMessageId;
          store.updateMessage(run.localAssistantId, {
            content: fullContent,
            serverMessageId: persistedId,
            turnId: event.turn_id || turnId,
            status: 'stopped',
          });
          terminal = true;
          break;
        } else if (event.type === 'response_complete') {
          fullContent = event.text || fullContent;
          const persistedId = event.assistant_message_id
            ? Number(event.assistant_message_id)
            : useChatStore.getState().messages.find((message) => message.id === run.localAssistantId)?.serverMessageId;
          store.updateMessage(run.localAssistantId, {
            content: fullContent,
            source: asResponseSource(event.source),
            documents: (event.documents as SourceDocument[]) || [],
            workflow: workflowFromEvent(event),
            serverMessageId: persistedId,
            turnId: event.turn_id || turnId,
            status: 'complete',
          });
          if (event.case_state) store.setActiveCase(event.case_state);
          if ((operation === 'retry' || operation === 'regenerate') && run.options.targetAssistantMessageId) {
            const replaced = useChatStore.getState().messages.find(
              (message) => message.serverMessageId === run.options.targetAssistantMessageId,
            );
            if (replaced) store.updateMessage(replaced.id, { status: 'superseded' });
          }
          terminal = true;
          lastFailedRunRef.current = null;
          break;
        } else if (event.type === 'error') {
          throw streamErrorFromEvent(event);
        }
      }
      if (!terminal) {
        throw new ChatStreamError({
          code: 'stream_incomplete',
          message: 'Luồng trả lời kết thúc trước khi nhận được trạng thái hoàn tất.',
          retryable: true,
          retryAfterSeconds: 2,
        });
      }
      await refreshSessionList();
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        const partial = fullContent || useChatStore.getState().streamingContent;
        store.updateMessage(run.localAssistantId, {
          content: partial,
          status: 'stopped',
        });
        await refreshSessionList();
      } else {
        const streamError = asStreamError(error);
        lastFailedRunRef.current = { ...run, options: { ...run.options, turnId } };
        store.setError(streamError);
        store.updateMessage(run.localAssistantId, {
          content: fullContent,
          status: 'failed',
        });
        toast.error(streamError.message);
      }
    } finally {
      if (activeTurnRef.current?.turnId === turnId) activeTurnRef.current = null;
      if (useChatStore.getState().activeTurn?.turnId === turnId) store.setActiveTurn(null);
      abortControllerRef.current = null;
      store.setStreaming(false);
      store.setStatusMessage('');
    }
  }, []);

  const sendMessage = useCallback(async (
    query: string,
    sessionId: string,
    mode: 'auto' | 'research_web' = 'auto',
    options: TurnOptions = {},
  ) => {
    if (useChatStore.getState().isStreaming) return;
    const turnId = crypto.randomUUID();
    const userMessage: ChatMessage = {
      id: `user-${turnId}`,
      role: 'user',
      content: query,
      timestamp: new Date().toISOString(),
      turnId,
      status: 'complete',
    };
    const assistantMessage = makeAssistant(turnId);
    const store = useChatStore.getState();
    store.addMessage(userMessage);
    store.addMessage(assistantMessage);
    ensureSessionVisibleInSidebar(sessionId, query);
    await runAssistantStream({
      query,
      sessionId,
      mode,
      options: { ...options, turnId },
      localAssistantId: assistantMessage.id,
    });
  }, [runAssistantStream]);

  const startReplay = useCallback(async (
    sessionId: string,
    targetMessageId: number,
    operation: Extract<TurnOperation, 'retry' | 'regenerate'>,
  ) => {
    if (useChatStore.getState().isStreaming) return;
    const turnId = crypto.randomUUID();
    const assistant = makeAssistant(turnId);
    useChatStore.getState().addMessage(assistant);
    await runAssistantStream({
      query: '',
      sessionId,
      mode: 'auto',
      options: {
        operation,
        turnId,
        targetAssistantMessageId: targetMessageId,
      },
      localAssistantId: assistant.id,
    });
  }, [runAssistantStream]);

  const regenerateResponse = useCallback(async (sessionId: string) => {
    const target = [...useChatStore.getState().messages]
      .reverse()
      .find((message) => message.role === 'assistant' && message.status === 'complete' && message.serverMessageId);
    if (target?.serverMessageId) await startReplay(sessionId, target.serverMessageId, 'regenerate');
  }, [startReplay]);

  const retryLastTurn = useCallback(async () => {
    const failed = lastFailedRunRef.current;
    if (!failed || useChatStore.getState().isStreaming) return;
    const failedMessage = useChatStore.getState().messages.find(
      (message) => message.id === failed.localAssistantId,
    );
    if (failedMessage?.serverMessageId) {
      await startReplay(failed.sessionId, failedMessage.serverMessageId, 'retry');
      return;
    }
    const turnId = crypto.randomUUID();
    const assistant = makeAssistant(turnId);
    useChatStore.getState().addMessage(assistant);
    await runAssistantStream({
      ...failed,
      options: { ...failed.options, turnId },
      localAssistantId: assistant.id,
    });
  }, [runAssistantStream, startReplay]);

  const stopGeneration = useCallback(() => {
    const turn = activeTurnRef.current || useChatStore.getState().activeTurn;
    if (!turn) return;
    const partial = useChatStore.getState().streamingContent;
    useChatStore.getState().updateMessage(turn.localAssistantId, {
      content: partial,
      status: 'stopped',
    });
    void sessionsApi.cancelTurn(turn.conversationId, turn.turnId).catch((error) => {
      console.warn('cancel turn failed:', error);
    });
    abortControllerRef.current?.abort();
  }, []);

  return {
    sendMessage,
    stopGeneration,
    regenerateResponse,
    retryLastTurn,
  };
}
