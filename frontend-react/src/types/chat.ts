/**
 * Chat-related type definitions
 */

export interface ChatMessage {
  id: string;
  serverMessageId?: number;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  source?: ResponseSource;
  documents?: SourceDocument[];
  workflow?: WorkflowMetadata;
  feedback?: { rating: 1 | 2; comment?: string | null };
  feedbackState?: 'idle' | 'pending' | 'saved' | 'failed';
  turnId?: string;
  status?: MessageStatus;
}

export type MessageStatus = 'pending' | 'streaming' | 'complete' | 'stopped' | 'failed' | 'superseded';

export type TurnOperation = 'message' | 'retry' | 'regenerate';

export interface StreamError {
  code: string;
  message: string;
  retryable: boolean;
  retryAfterSeconds?: number | null;
  traceId?: string;
  pipelineVersion?: string;
}

export interface ActiveTurn {
  turnId: string;
  conversationId: string;
  localAssistantId: string;
  assistantMessageId?: number;
  operation: TurnOperation;
}

export type ResponseSource = 
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
  context_loaded?: boolean;
  history_messages?: number;
  is_follow_up?: boolean;
  standalone_query?: string;
  task_type?: string;
  route?: string;
  source_scope?: string;
  corpus_version?: string;
  corpus_sha?: string;
  embedding_profile?: string;
  evidence_status?: string;
  available_actions?: string[];
  assessment?: Record<string, unknown> | null;
  checklist?: Array<Record<string, unknown>>;
  assumptions?: string[];
  citations?: Array<Record<string, unknown>>;
  evidence_assessment?: EvidenceAssessment;
  trace_id?: string;
  corpus_id?: string;
  pipeline_version?: string;
  termination_reason?: string;
  outcome?: 'completed' | 'needs_information' | 'insufficient_evidence' | 'out_of_scope' | 'failed';
  result_type?: 'legal_answer' | 'assessment' | 'checklist' | 'none';
  required_issues?: string[];
  covered_issues?: string[];
  rule_id?: string;
  effective_dates?: Record<string, string>;
  corpus_as_of_date?: string;
  sources?: SourceSnapshot[];
  replay_metadata?: Record<string, unknown>;
  citation_error?: string;
  safe_stop_reason?: string;
  preview?: boolean;
  steps?: WorkflowStep[];
  redline_report?: Record<string, unknown>;
  calculator_result?: Record<string, unknown>;
  document_draft?: Record<string, unknown>;
}

export interface SourceSnapshot {
  citation_index?: number;
  citation_indices?: number[];
  source_id: string;
  chunk_id?: string;
  title?: string;
  instrument_number?: string;
  anchor?: string;
  page?: string | number | null;
  offset_start?: number | null;
  offset_end?: number | null;
  official_url?: string;
  effective_status?: string;
  effective_from?: string | null;
  effective_to?: string | null;
  amendment_relationship?: string[] | Record<string, unknown>;
  active_source_document_id?: string;
  active_source_pages?: string;
  amendment_resolution_status?: string;
  amendment_operations?: Array<Record<string, unknown>>;
  current_law_support?: boolean;
  corpus_as_of_date?: string;
  excerpt?: string;
  source_kind?: string;
  authority?: string;
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
  label?: string;
  status: string;
  trace_id?: string;
  pipeline_version?: string;
  sequence?: number;
  details?: unknown;
  latency_ms?: number;
  args?: Record<string, unknown>;
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  created_at: number;
  updated_at?: number;
}
