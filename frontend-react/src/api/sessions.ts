import apiClient from './client';
import type { CaseState, SessionInfo, SessionDetail } from '@/types';

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
  facts: Record<string, string>,
  taskType?: CaseState['task_type'],
  confirmationStatuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'> = {}
): Promise<CaseState> {
  const response = await apiClient.patch<CaseState>(`${SESSIONS_ENDPOINT}/${sessionId}/case`, {
    facts,
    fact_updates: Object.fromEntries(Object.entries(facts).map(([key, value]) => [key, {
      value,
      confirmation_status: confirmationStatuses[key] || 'user_confirmed',
    }])),
    task_type: taskType,
  });
  return response.data;
}
