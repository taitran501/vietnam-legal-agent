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
  route?: string;
  source_scope?: string;
  corpus_version?: string;
  corpus_sha?: string;
  embedding_profile?: string;
  evidence_status?: string;
  available_actions?: string[];
  case_state?: CaseState | null;
  assessment?: Record<string, unknown> | null;
  checklist?: Array<Record<string, unknown>>;
  assumptions?: string[];
  missing_facts?: string[];
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
}

export type CaseFacts = Record<string, string | FactValue>;

export interface FactValue {
  value: string;
  source: 'user_turn' | 'case_panel' | 'system_default';
  source_turn?: string;
  evidence_span?: string;
  confidence?: number;
  verified?: boolean;
}

export interface CaseField {
  key: string;
  label: string;
  kind: 'text' | 'select' | 'number' | 'boolean';
  options: Array<{ value: string; label: string }>;
  required: boolean;
  missing: boolean;
  value: string;
  help_text?: string;
}

export interface CaseState {
  task_type: 'assess_epr_obligation' | 'build_compliance_checklist';
  status: 'collecting' | 'ready' | 'completed';
  facts: CaseFacts;
  missing_facts: string[];
  last_query?: string;
  updated_at?: number;
  schema_version?: string;
  decision_status?: string | null;
  issue_states?: Record<string, unknown>;
  as_of_date?: string;
  fields?: CaseField[];
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
