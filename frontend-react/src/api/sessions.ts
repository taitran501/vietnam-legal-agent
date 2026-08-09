import apiClient from './client';
import type { CaseState, CaseFacts, SessionInfo, SessionDetail } from '@/types';

const SESSIONS_ENDPOINT = '/api/v1/sessions';

/**
 * List all sessions
 */
export async function listSessions(limit = 50): Promise<SessionInfo[]> {
  const response = await apiClient.get<SessionInfo[]>(SESSIONS_ENDPOINT, {
    params: { limit },
  });
  return response.data;
}

/**
 * Get session details
 */
export async function getSession(sessionId: string): Promise<SessionDetail> {
  const response = await apiClient.get<SessionDetail>(
    `${SESSIONS_ENDPOINT}/${sessionId}`
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

export async function getCaseState(sessionId: string): Promise<CaseState | null> {
  const response = await apiClient.get<CaseState | null>(`${SESSIONS_ENDPOINT}/${sessionId}/case`);
  return response.data;
}

export async function updateCaseState(
  sessionId: string,
  facts: CaseFacts,
  taskType?: CaseState['task_type']
): Promise<CaseState> {
  const response = await apiClient.patch<CaseState>(`${SESSIONS_ENDPOINT}/${sessionId}/case`, {
    facts,
    task_type: taskType,
  });
  return response.data;
}
