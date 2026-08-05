/**
 * Chat-related type definitions
 */

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  source?: ResponseSource;
  documents?: SourceDocument[];
}

export type ResponseSource = 
  | 'faq'
  | 'legal'
  | 'chitchat'
  | 'web_search'
  | 'cache'
  | 'follow_up'
  | 'error';

export interface SourceDocument {
  page_content: string;
  document_id?: string;
  score?: number | null;
  source?: string;
  metadata: {
    Dieu?: string;
    Chuong?: string;
    [key: string]: unknown;
  };
}

export interface WorkflowMetadata {
  task_type?: string;
  assessment?: Record<string, unknown> | null;
  checklist?: Array<Record<string, unknown>>;
  assumptions?: string[];
  missing_facts?: string[];
  citations?: Array<Record<string, unknown>>;
  trace_id?: string;
  termination_reason?: string;
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  created_at: number;
  updated_at?: number;
}
