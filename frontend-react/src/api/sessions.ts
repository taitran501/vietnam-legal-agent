import apiClient from './client';
import type { SessionInfo, SessionDetail } from '@/types';

const SESSIONS_ENDPOINT = '/api/v1/sessions';

/**
 * List all sessions
 */
export async function listSessions(
  limit = 30,
  offset = 0,
  q = '',
  signal?: AbortSignal,
): Promise<SessionInfo[]> {
  const response = await apiClient.get<SessionInfo[]>(SESSIONS_ENDPOINT, {
    params: { limit, offset, q },
    signal,
  });
  return response.data;
}

/**
 * Get session details
 */
export async function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionDetail> {
  const response = await apiClient.get<SessionDetail>(
    `${SESSIONS_ENDPOINT}/${sessionId}`,
    { signal },
  );
  return response.data;
}

/**
 * Delete session
 */
export async function deleteSession(sessionId: string): Promise<void> {
  await apiClient.delete(`${SESSIONS_ENDPOINT}/${sessionId}`);
}

/**
 * Update session title
 */
export async function updateSession(
  sessionId: string,
  title: string
): Promise<SessionInfo> {
  const response = await apiClient.patch<SessionInfo>(
    `${SESSIONS_ENDPOINT}/${sessionId}`,
    { title }
  );
  return response.data;
}

export async function cancelTurn(sessionId: string, turnId: string): Promise<void> {
  await apiClient.put(`/api/v1/conversations/${sessionId}/turns/${turnId}/cancel`);
}
