/**
 * API request/response type definitions
 */

import type { SourceDocument, WorkflowMetadata } from './chat';

export interface ChatRequest {
  query: string;
  session_id?: string;
  faq_threshold?: number;
}

export interface SSEEvent {
  type: 'status' | 'workflow_step' | 'response_chunk' | 'response_complete' | 'error';
  message?: string;
  chunk?: string;
  text?: string;
  documents?: SourceDocument[];
  source?: string;
  stage?: string;
  step?: number;
  action?: string;
  status?: string;
  trace_id?: string;
  task_type?: string;
  assessment?: Record<string, unknown> | null;
  checklist?: Array<Record<string, unknown>>;
  assumptions?: string[];
  missing_facts?: string[];
  citations?: Array<Record<string, unknown>>;
  termination_reason?: string;
  metadata?: WorkflowMetadata;
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
