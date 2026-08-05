import apiClient from './client';
import type { FeedbackRequest, FeedbackResponse } from '@/types';

const FEEDBACK_ENDPOINT = '/api/v1/feedback';

/**
 * Submit feedback
 */
export async function submitFeedback(
  data: FeedbackRequest
): Promise<FeedbackResponse> {
  const response = await apiClient.post<FeedbackResponse>(
    FEEDBACK_ENDPOINT,
    data
  );
  return response.data;
}
