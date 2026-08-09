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
  workflow?: WorkflowMetadata;
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
  case_state?: CaseState | null;
  assessment?: Record<string, unknown> | null;
  checklist?: Array<Record<string, unknown>>;
  assumptions?: string[];
  missing_facts?: string[];
  citations?: Array<Record<string, unknown>>;
  evidence_assessment?: EvidenceAssessment;
  trace_id?: string;
  termination_reason?: string;
}

export interface CaseFacts {
  business_role?: string;
  product_or_packaging?: string;
  material?: string;
  activity_scope?: string;
}

export interface CaseState {
  task_type: 'assess_epr_obligation' | 'build_compliance_checklist';
  status: 'collecting' | 'ready' | 'completed';
  facts: CaseFacts;
  missing_facts: string[];
  last_query?: string;
  updated_at?: number;
}

export interface EvidenceAssessment {
  sufficient?: boolean;
  reason?: string;
  documents_considered?: number;
  total_chars?: number;
  has_legal_metadata?: boolean;
}

export interface WorkflowStep {
  step: number;
  action: string;
  status: string;
  trace_id?: string;
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  created_at: number;
  updated_at?: number;
}
