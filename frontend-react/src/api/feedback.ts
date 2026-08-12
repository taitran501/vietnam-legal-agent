import apiClient from './client';
import type { FeedbackRequest, FeedbackResponse } from '@/types';

const FEEDBACK_ENDPOINT = '/api/v1/feedback';

/**
 * Submit feedback
 */
export async function submitFeedback(
  data: FeedbackRequest
): Promise<FeedbackResponse> {
  const response = data.message_id && data.session_id
    ? await apiClient.put<FeedbackResponse>(`/api/v1/conversations/${data.session_id}/messages/${data.message_id}/feedback`, {
      rating: data.rating,
      comment: data.comment,
    })
    : await apiClient.post<FeedbackResponse>(FEEDBACK_ENDPOINT, data);
  return response.data;
}
