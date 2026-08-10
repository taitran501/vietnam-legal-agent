import type { SSEEvent } from '@/types';

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
  options: {
    operation?: 'message' | 'continue_case';
    intentHint?: 'auto' | 'legal_lookup' | 'legal_explain_compare' | 'case_assessment' | 'compliance_checklist';
    interactionSource?: 'composer' | 'quick_action' | 'case_panel';
    casePatch?: Record<string, string>;
  } = {},
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
      ...(import.meta.env.VITE_API_KEY ? { 'X-API-Key': import.meta.env.VITE_API_KEY } : {}),
    },
    body: JSON.stringify({
      query,
      conversation_id: conversationId,
      mode,
      operation: options.operation || 'message',
      intent_hint: options.intentHint || 'auto',
      interaction_source: options.interactionSource || 'composer',
      case_patch: options.casePatch || {},
    }),
    signal,
  });

  if (!response.ok) {
    const payload = await response.text();
    const event = parseSSEEvent(payload);
    throw new Error(event?.message || `HTTP ${response.status}: ${response.statusText}`);
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
