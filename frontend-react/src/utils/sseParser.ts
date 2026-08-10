import type { SSEEvent } from '@/types';

/**
 * Parse SSE event stream from response
 */
export function parseSSEEvent(line: string): SSEEvent | null {
  if (!line.startsWith('data: ')) {
    return null;
  }

  const raw = line.slice(6).trim();
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as SSEEvent;
  } catch {
    console.error('Failed to parse SSE event:', raw);
    return null;
  }
}

/**
 * Stream chat response using fetch + ReadableStream
 */
export async function* streamChat(
  query: string,
  conversationId: string,
  signal?: AbortSignal
): AsyncGenerator<SSEEvent> {
  // Use relative URL for Vite proxy, or full URL if needed
  const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
  const url = baseUrl ? `${baseUrl}/api/v1/chat` : '/api/v1/chat';
  
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(import.meta.env.VITE_API_KEY ? { 'X-API-Key': import.meta.env.VITE_API_KEY } : {}),
    },
    body: JSON.stringify({
      query,
      conversation_id: conversationId,
    }),
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
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
      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; // Keep incomplete line in buffer

      for (const line of lines) {
        const event = parseSSEEvent(line);
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
