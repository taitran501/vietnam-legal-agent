/**
 * API request/response type definitions
 */

import type { SourceDocument } from './chat';

export interface ChatRequest {
  query: string;
  session_id?: string;
  faq_threshold?: number;
}

export interface SSEEvent {
  type: 'status' | 'response_chunk' | 'response_complete' | 'error';
  message?: string;
  chunk?: string;
  text?: string;
  documents?: SourceDocument[];
  source?: string;
  stage?: string;
}

export interface SessionInfo {
  id: string;
  title: string;
  created_at: number;
  updated_at?: number;
  message_count: number;
}

export interface SessionDetail {
  id: string;
  title: string;
  messages: Array<{
    role: string;
    content: string;
    timestamp: string;
  }>;
  created_at: number;
  updated_at?: number;
  message_count: number;
}

export interface FeedbackRequest {
  session_id: string;
  message_index: number;
  rating: 1 | 2; // 1 = thumbs down, 2 = thumbs up
  comment?: string;
}

export interface FeedbackResponse {
  status: 'ok' | 'error';
  message?: string;
  detail?: string;
}

export interface HealthResponse {
  status: string;
  qdrant: string;
  redis: string;
  openai: string;
}
