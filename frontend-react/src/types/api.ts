/**
 * API request/response type definitions
 */

import type { CaseState, EvidenceAssessment, SourceDocument, WorkflowMetadata } from './chat';

export interface ChatRequest {
  query: string;
  conversation_id?: string;
  session_id?: string;
  mode?: 'auto' | 'research_web';
  operation?: 'message' | 'continue_case';
  intent_hint?: 'auto' | 'legal_lookup' | 'legal_explain_compare' | 'case_assessment' | 'compliance_checklist';
  interaction_source?: 'composer' | 'quick_action' | 'case_panel';
  case_patch?: Record<string, string>;
  fact_updates?: Record<string, { value: string; confirmation_status?: 'user_confirmed' | 'document_verified' | 'unknown' }>;
  replay_metadata?: Record<string, unknown>;
}

export interface SSEEvent {
  type: 'status' | 'workflow_step' | 'response_chunk' | 'response_complete' | 'case_update' | 'input_required' | 'error';
  message?: string;
  chunk?: string;
  chunk_index?: number;
  chunk_count?: number;
  text?: string;
  documents?: SourceDocument[];
  source?: string;
  stage?: string;
  step?: number;
  action?: string;
  label?: string;
  status?: string;
  sequence?: number;
  trace_id?: string;
  task_type?: string;
  route?: string;
  source_scope?: string;
  corpus_version?: string;
  corpus_sha?: string;
  embedding_profile?: string;
  evidence_status?: string;
  available_actions?: string[];
  assessment?: Record<string, unknown> | null;
  case_state?: CaseState | null;
  checklist?: Array<Record<string, unknown>>;
  assumptions?: string[];
  missing_facts?: string[];
  citations?: Array<Record<string, unknown>>;
  evidence_assessment?: EvidenceAssessment;
  termination_reason?: string;
  corpus_id?: string;
  pipeline_version?: string;
  outcome?: WorkflowMetadata['outcome'];
  result_type?: WorkflowMetadata['result_type'];
  required_issues?: string[];
  covered_issues?: string[];
  rule_id?: string;
  rule_pack_version?: string;
  effective_dates?: Record<string, string>;
  metadata?: WorkflowMetadata;
  code?: string;
  retryable?: boolean;
  retry_after_seconds?: number;
  assistant_message_id?: string;
  corpus_as_of_date?: string;
  sources?: import('./chat').SourceSnapshot[];
  replay_metadata?: Record<string, unknown>;
  validation_errors?: Record<string, string>;
  citation_error?: string;
  safe_stop_reason?: string;
}

export interface SessionInfo {
  id: string;
  title: string;
  created_at: number;
  updated_at?: number;
  message_count: number;
  archived?: boolean;
  pinned?: boolean;
}

export interface SessionDetail {
  id: string;
  title: string;
  messages: Array<{
    id?: number;
    role: string;
    content: string;
    timestamp: string;
    metadata?: WorkflowMetadata & { sources?: import('./chat').SourceSnapshot[] };
  }>;
  created_at: number;
  updated_at?: number;
  message_count: number;
}

export interface FeedbackRequest {
  session_id: string;
  message_index?: number;
  message_id?: number;
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

export interface ReadinessResponse {
  status: 'ready' | 'not_ready';
  dependencies: Record<string, 'ok' | 'error'>;
  corpus: {
    status: 'ready' | 'missing' | 'version_mismatch' | 'promotion_blocked' | 'incomplete';
    points_count: number;
    corpus_id: string;
    corpus_version: string;
    index_schema_version: string;
    corpus_sha?: string;
    embedding_profile?: string;
    embedding_dimensions?: number;
    corpus_as_of_date?: string | null;
    source_completeness?: string;
    amendment_chain_status?: string;
    promotion_status?: string;
  };
}
