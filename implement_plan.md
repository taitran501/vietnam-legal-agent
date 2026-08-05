# Real Chat History Implementation TODO

## Current Status (Implemented)
- [x] Added persistent history store module with SQLite backend.
- [x] Added durable tables: users, conversations, messages, conversation_summaries.
- [x] Added ownership checks at store layer (conversation cannot be hijacked by another user).
- [x] Added startup initialization for persistent history store.
- [x] Extended chat request schema with conversation_id while keeping session_id compatibility.
- [x] Updated chat route to use user_id + conversation_id and return X-Conversation-ID.
- [x] Integrated pipeline read/write with persistent history (with dual-write compatibility to legacy session store).
- [x] Updated sessions API to read/write persistent conversations per user (with legacy fallback).
- [x] Added tests for persistent history store and passed regressions.
- [x] Added explicit create conversation endpoint.
- [x] Added archive or unarchive endpoint.
- [x] Added pin or unpin endpoint.
- [x] Added cursor-based messages endpoint.
- [x] Added Redis-to-persistent migration script scaffold.

## Next Immediate TODO (In Progress)
- [x] Add API integration tests for sessions endpoints (create/list/get/update/archive/pin/messages/delete).
- [ ] Add migration dry-run command and verification report output.
- [ ] Add feature flag rollout path and telemetry dashboards.

## Goal
- Build account-level, durable chat history (not session-only memory).
- Keep compatibility with current flow during migration.

## Priority Legend
- P0: Must have for correct product behavior.
- P1: Important quality and rollout safety.
- P2: Nice to have enhancements.

## Sprint 0 - Design Freeze and Scope Lock (P0)
- [ ] Define final product behavior for history:
	- account-level ownership
	- cross-device continuity
	- delete/archive/rename behavior
	- retention policy
- [ ] Decide database engine and migration tool.
- [ ] Define conversation context policy for inference:
	- latest N turns
	- summary usage
	- long-term retrieval limits
- [ ] Write API contract draft and review with frontend.

Acceptance:
- [ ] One approved design doc with schema, API, and context policy.

## Sprint 1 - Persistent Data Model and Ownership (P0)

### 1.1 Schema
- [ ] Create users table (if not already present in auth domain).
- [ ] Create conversations table:
	- id, user_id, title, archived, pinned, created_at, updated_at
- [ ] Create messages table:
	- id, conversation_id, role, content, model, metadata, created_at
- [ ] Create conversation_summaries table (optional in this sprint):
	- conversation_id, short_summary, last_updated
- [ ] Add indexes:
	- conversations(user_id, updated_at desc)
	- messages(conversation_id, created_at asc)

### 1.2 Ownership and security
- [ ] Enforce ownership at repository/service layer.
- [ ] Add authorization checks for all conversation and message reads/writes.

### 1.3 Redis role reduction
- [ ] Keep Redis for cache/hot path only.
- [ ] Remove Redis as source of truth for long-term history.

Acceptance:
- [ ] DB migration runs clean on local and staging.
- [ ] User A cannot read User B conversation or messages.

## Sprint 2 - Conversation and Message APIs (P0)

### 2.1 Conversation endpoints
- [x] POST create conversation.
- [ ] GET list conversations (cursor pagination).
- [ ] GET conversation detail.
- [ ] PATCH rename conversation.
- [x] PATCH archive or unarchive conversation.
- [x] PATCH pin or unpin conversation.
- [ ] DELETE conversation.

### 2.2 Message endpoints
- [x] GET list messages in conversation (cursor pagination).
- [ ] POST append user message and assistant response.
- [ ] Optional: POST regenerate response as a new branch.

### 2.3 Backward compatibility
- [ ] If legacy client sends only session_id, map it to conversation_id.
- [ ] Return deprecation signal for session-only mode.

Acceptance:
- [ ] API integration tests pass for CRUD and pagination.
- [ ] Legacy request still works through compatibility adapter.

## Sprint 3 - Pipeline Integration (P0)

### 3.1 Identity inputs
- [ ] Replace session_id-first pipeline signature with user_id + conversation_id.
- [ ] Validate conversation ownership before loading context.

### 3.2 Context loading
- [ ] Load latest N turns from persistent messages.
- [ ] Add summary context if available.
- [ ] Add top K semantically relevant historical snippets (if enabled).

### 3.3 Persistence on response
- [ ] Persist user message and assistant message to DB after generation.
- [ ] Keep semantic answer cache write path unchanged.

Acceptance:
- [ ] Closing and reopening browser resumes same conversation.
- [ ] Restarting backend does not lose history.

## Sprint 4 - Long-Context Memory Strategy (P1)

### 4.1 Summarization
- [ ] Add rolling summary update when token budget exceeds threshold.
- [ ] Store summary versions and updated timestamps.

### 4.2 Semantic recall
- [ ] Embed messages asynchronously.
- [ ] Store message embeddings for retrieval.
- [ ] Retrieve top K historical messages by semantic relevance.

### 4.3 Context assembly order
- [ ] system instructions
- [ ] conversation summary
- [ ] relevant historical snippets
- [ ] recent turns

Acceptance:
- [ ] Long conversation remains coherent without context overflow.
- [ ] Context build latency stays within SLO budget.

## Sprint 5 - Frontend UX for Real History (P0)
- [ ] Sidebar list with conversation title and updated time.
- [ ] Open old conversation and continue chatting.
- [ ] New chat creates new conversation_id.
- [ ] Rename, archive, delete actions.
- [ ] Search history by title and message content.

Acceptance:
- [ ] User can continue old conversation across devices after login.

## Sprint 6 - Migration and Rollout (P1)

### 6.1 Dual write
- [ ] Write history to both old session store and new DB during transition.

### 6.2 Data migration
- [x] Build migration script from important Redis sessions to DB.
- [ ] Run dry-run and verify row counts and sample quality.

### 6.3 Feature flags
- [ ] Enable for internal users first.
- [ ] Monitor errors and latency.
- [ ] Ramp to all users.

### 6.4 Decommission old path
- [ ] Remove session-history-as-truth code after stabilization window.

Acceptance:
- [ ] No history regression during rollout.

## Sprint 7 - Reliability, Security, Observability (P1)
- [ ] Metrics:
	- message write success rate
	- history load latency
	- context build latency
	- semantic recall hit quality
- [ ] Add audit logs for conversation CRUD.
- [ ] Add retention and deletion jobs (privacy compliance).
- [ ] Add concurrency guard for message ordering in fast multi-send scenarios.

Acceptance:
- [ ] On-call dashboards and alerts are live.
- [ ] Privacy delete request removes all owned history.

## Testing Checklist (Continuous)
- [ ] Unit tests for repositories and context builder.
- [ ] API tests for auth, ownership, pagination, CRUD.
- [ ] Pipeline tests for context correctness and persistence.
- [ ] Migration tests for compatibility adapter.
- [ ] Load tests for history-heavy conversations.

## Final Definition of Done
- [ ] User can close browser and continue later in same conversation.
- [ ] User can continue same conversation from another device.
- [ ] History survives backend restart and deployment.
- [ ] Conversation list and operations (open, rename, archive, delete) are stable.
- [ ] Pipeline latency remains within target with history enabled.
