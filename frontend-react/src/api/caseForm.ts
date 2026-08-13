import apiClient from './client';
import type { CaseFormState, CaseState } from '@/types';

export interface CaseFormFactUpdate {
  value: string;
  confirmation_status?: 'user_confirmed' | 'document_verified' | 'unknown';
}

export async function resolveCaseForm(
  taskType: CaseState['task_type'],
  factUpdates: Record<string, CaseFormFactUpdate>,
  signal?: AbortSignal,
): Promise<CaseFormState> {
  const response = await apiClient.post<CaseFormState>(
    '/api/v1/case-form/resolve',
    { task_type: taskType, fact_updates: factUpdates },
    { signal },
  );
  return response.data;
}
