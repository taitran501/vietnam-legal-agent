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
  | 'error';

export interface SourceDocument {
  page_content: string;
  metadata: {
    Dieu?: string;
    Chuong?: string;
    [key: string]: unknown;
  };
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  created_at: number;
  updated_at?: number;
}
