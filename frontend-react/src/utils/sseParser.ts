import type { SSEEvent } from '@/types';
import { authorizationHeader, handleUnauthorized } from '@/auth/oidc';
import type { StreamError, TurnOperation } from '@/types';

export class ChatStreamError extends Error implements StreamError {
  code: string;
  retryable: boolean;
  retryAfterSeconds?: number | null;
  traceId?: string;
  pipelineVersion?: string;

  constructor(payload: StreamError) {
    super(payload.message);
    this.name = 'ChatStreamError';
    this.code = payload.code;
    this.retryable = payload.retryable;
    this.retryAfterSeconds = payload.retryAfterSeconds;
    this.traceId = payload.traceId;
    this.pipelineVersion = payload.pipelineVersion;
  }
}

export interface StreamTurnOptions {
  operation?: TurnOperation;
  intentHint?: 'auto' | 'legal_lookup' | 'legal_explain_compare' | 'case_assessment' | 'compliance_checklist';
  interactionSource?: 'composer' | 'quick_action' | 'case_panel';
  casePatch?: Record<string, string>;
  factUpdates?: Record<string, { value: string; confirmation_status?: 'user_confirmed' | 'document_verified' | 'unknown' }>;
  replayMetadata?: Record<string, unknown>;
  turnId?: string;
  targetAssistantMessageId?: number;
}

export function streamErrorFromEvent(event: SSEEvent): ChatStreamError {
  return new ChatStreamError({
    code: event.code || 'pipeline_error',
    message: event.message || 'Không thể hoàn tất yêu cầu.',
    retryable: Boolean(event.retryable),
    retryAfterSeconds: event.retry_after_seconds,
    traceId: event.trace_id,
    pipelineVersion: event.pipeline_version,
  });
}

/**
 * Parse one complete SSE frame from a response stream.
 *
 * The server currently serialises each JSON event on one ``data:`` line, but
 * this parser also accepts standard multi-line SSE data and CRLF framing.
 */
export function parseSSEEvent(frame: string): SSEEvent | null {
  const dataLines = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''));

  if (dataLines.length === 0) {
    return null;
  }

  const raw = dataLines.join('\n').trim();
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as SSEEvent;
  } catch {
    // A malformed or partial frame must not terminate a healthy stream.
    return null;
  }
}

/**
 * Stream chat response using fetch + ReadableStream
 */
export async function* streamChat(
  query: string,
  conversationId: string,
  signal?: AbortSignal,
  mode: 'auto' | 'research_web' = 'auto',
  options: StreamTurnOptions = {},
): AsyncGenerator<SSEEvent> {
  // Use relative URL for Vite proxy, or full URL if needed
  const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
  const url = baseUrl ? `${baseUrl}/api/v1/chat` : '/api/v1/chat';
  
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'Cache-Control': 'no-cache',
      ...authorizationHeader(),
    },
    body: JSON.stringify({
      query,
      conversation_id: conversationId,
      turn_id: options.turnId,
      mode,
      operation: options.operation || 'message',
      target_assistant_message_id: options.targetAssistantMessageId,
      intent_hint: options.intentHint || 'auto',
      interaction_source: options.interactionSource || 'composer',
      case_patch: options.casePatch || {},
      fact_updates: options.factUpdates || {},
      replay_metadata: options.replayMetadata || {
        query_mode: mode,
        intent: options.intentHint || 'auto',
        operation: options.operation || 'message',
        interaction_source: options.interactionSource || 'composer',
        case_patch: options.casePatch || {},
      },
    }),
    signal,
  });

  if (!response.ok) {
    const payload = await response.text();
    const event = parseSSEEvent(payload);
    if (response.status === 401) handleUnauthorized();
    if (event?.type === 'error') throw streamErrorFromEvent(event);
    throw new ChatStreamError({
      code: response.status === 401 ? 'authentication_required' : `http_${response.status}`,
      message: response.status === 401
        ? 'Phiên đăng nhập đã hết hạn.'
        : 'Không thể kết nối tới dịch vụ trả lời.',
      retryable: response.status >= 500 || response.status === 429,
      retryAfterSeconds: response.status === 429 ? 30 : response.status >= 500 ? 2 : null,
    });
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Response body is not readable');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || ''; // Keep an incomplete frame in the buffer.

      for (const frame of frames) {
        const event = parseSSEEvent(frame);
        if (event) {
          yield event;
        }
      }
    }

    // Process remaining buffer
    if (buffer) {
      const event = parseSSEEvent(buffer);
      if (event) {
        yield event;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
