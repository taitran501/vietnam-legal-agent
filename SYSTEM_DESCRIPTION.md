## EPR Chatbot System Description

This document describes the full system implemented in the `epr_chatbot` repository, including architecture, components, runtime flow, ingestion/indexing, storage dependencies, deployment, and test/evaluation code.

All statements below are grounded in the repository contents and reflect the behavior of the current code.

---

## 1. High-Level Overview

`epr_chatbot` is a Vietnamese legal Q&A chatbot specialized for:
- The EPR (Trách nhiệm mở rộng của nhà sản xuất) domain
- Nghị định `08/2022/NĐ-CP` (and related EPR legal scope)

The system is composed of:
- A FastAPI backend that streams responses to the client via SSE
- A Streamlit frontend that renders chat UI and consumes the SSE stream
- Retrieval and generation modules built with LangChain/LangChain OpenAI
- A Qdrant vector database for:
  - Law and FAQ retrieval
  - Semantic cache matching (answers cache)
- Redis for storing chat session history
- Optional Tavily web search fallback (when internal retrieval fails)
- Optional LangSmith tracing for observability

---

## 2. Repository Codebase Structure

Repository root layout (key directories/files):

- `README.md`
- `data/`
  - `faq.json`
  - `law.json`
- `backend/`
  - `main.py`
  - `config.py`
  - `api/`
    - `schemas.py`
    - `routes/`
      - `chat.py`
      - `health.py`
  - `core/`
    - `pipeline.py`
    - `retrieval.py`
    - `generation.py`
    - `router.py`
    - `rewriter.py`
    - `llm_instances.py`
  - `cache/`
    - `semantic_cache.py`
  - `memory/`
    - `session_store.py`
- `frontend/`
  - `app.py`
- `scripts/`
  - `build_index.py`
  - `add_phuluc_xxii.py`
  - `eda_law.py`
  - `start_redis.ps1`
- `tests/`
  - `eval/`
    - `run_eval.py`
    - `evaluators.py`
    - `compact_stored_results.py` (optional: shrink `results_*.json` on disk)
    - `diagnose.py`
    - `results_*.json` (stored eval outputs; committed copies are compacted: no `final_text`)
- Deployment/config:
  - `docker-compose.yml`
  - `nginx.conf`
  - `Dockerfile.backend`
  - `Dockerfile.frontend`
  - `requirements/backend.txt`
  - `requirements/frontend.txt`
  - `.env.example`
  - `.gitignore`

Notes:
- When `use_qdrant_cloud=false`, Qdrant local storage is written under `qdrant_db/` (this directory is gitignored and not part of the source-of-truth content on GitHub).
- The repo contains an `.env` file, but secrets are not described here; only `.env.example` is used as documentation of expected variables.

---

## 3. Runtime Architecture (Online Serving)

### 3.1 Backend API (FastAPI)

Entry point:
- `backend/main.py`

Responsibilities:
- Create a `FastAPI` application.
- Configure CORS using `ALLOWED_ORIGINS` env var (default includes:
  `http://localhost` and `http://localhost:8501`).
- On startup (lifespan):
  - Ping Redis (best-effort; failures degrade session persistence gracefully).
  - Ensure FAQ Qdrant collection exists and is populated by calling:
    - `backend.core.retrieval.ensure_faq_collection()`
- Register routers:
  - Chat endpoint under `/api/v1`:
    - `backend.api.routes.chat.router`
  - Health endpoint under `/api/v1`:
    - `backend.api.routes.health.router`

#### Chat endpoint

File:
- `backend/api/routes/chat.py`

Endpoint:
- `POST /api/v1/chat`

Behavior:
- Returns `text/event-stream` using `sse_starlette.sse.EventSourceResponse`.
- Internally calls `backend.core.pipeline.optimized_chatbot_pipeline(...)`.
- The endpoint yields each pipeline event as JSON:
  - `{"data": json.dumps(event, ensure_ascii=False)}`

#### Health endpoint

File:
- `backend/api/routes/health.py`

Endpoint:
- `GET /api/v1/health`

Behavior:
- Checks:
  - Qdrant connectivity via `_get_qdrant_client().get_collections()`
  - Redis connectivity via `await get_redis().ping()`
- Returns `HealthResponse(status="ok"|"degraded", qdrant=..., redis=...)`.

### 3.2 Frontend (Streamlit)

File:
- `frontend/app.py`

Responsibilities:
- Maintain UI state using:
  - `st.session_state.session_id`
  - `st.session_state.messages` (list of `{role, content}`)
- Render chat history using `st.chat_message`.
- Provide an input box `st.chat_input`.
- On submit:
  - Append the user message to `st.session_state.messages`
  - Stream assistant output from backend `/api/v1/chat`
  - Parse SSE lines that start with `data:` and decode JSON
  - Display:
    - `status` events via a caption placeholder
    - `response_chunk` events by incrementally appending token chunks
    - `response_complete` event by finalizing the message
  - Display source badge (`faq`, `legal`, `web_search`, `chitchat`, `cache`)
  - Optionally show referenced documents in an expander
  - Append the finalized assistant message to `st.session_state.messages`
- Sidebar controls:
  - “New Chat” generates a new UUID session id and clears `messages`
  - Slider for `faq_threshold`
  - Export conversation to PDF (if there is chat history)

Backend streaming protocol:
- Frontend expects pipeline events to match the format documented in:
  `backend/core/pipeline.py`:
  - `type`: `status` | `response_chunk` | `response_complete`

---

## 4. Core Chatbot Pipeline

File:
- `backend/core/pipeline.py`

Primary function:
- `optimized_chatbot_pipeline(query, session_id="default", faq_threshold=0.75, skip_cache=False)`

Type:
- async generator that yields pipeline events until completion

Input/Output contract:
- Yields:
  - `{"type": "status", "message": str, "stage": str}`
  - `{"type": "response_chunk", "chunk": str, "stage": "streaming"}`
  - `{"type": "response_complete", "text": str, "documents": [...], "source": str, "stage": "complete"}`

### 4.1 Pipeline Flow

Order of stages in `optimized_chatbot_pipeline`:

0. Load conversation history
   - Uses persistent history (`backend/history/store.py`) when enabled.
   - Falls back to Redis session store on error.

1. Semantic cache lookup (unless `skip_cache=True`)
   - `semantic_cache.lookup(query)` (Redis exact first, then Qdrant semantic cache)
   - On hit: return immediately with `source="cache"`.

2. Route question
   - `router.route_query(query)` -> `chitchat` or `epr_query`.
   - `chitchat` path generates friendly response and exits (not semantic-cached).

3. Conditional rewrite (substantive path only)
   - Rewrite runs only when query looks context-dependent (ambiguous follow-up).
   - Explicit legal references (e.g. `Điều 77`) are not rewritten.

4. Strict FAQ semantic cache
   - `retrieval.retrieve_faq_async(effective_query, faq_threshold)`
   - FAQ is returned only when `strict_faq_hit=True`:
     - high similarity
     - enough margin vs runner-up
     - query is not legal-specific
   - Non-strict FAQ candidates do not short-circuit; pipeline continues to legal retrieval.

5. Legal retrieval (hybrid)
   - `retrieval.retrieve_legal_async(effective_query)` -> `retrieve_legal()` -> `retrieve_legal_ensemble()`
   - Candidate generation combines:
     - semantic dense retrieval (Qdrant cosine)
     - lexical BM25-style retrieval (in-memory index)
     - explicit article lookup for `Điều X` mentions
   - Candidates are merged and reranked.

5-pre. “Article not found” shortcut
   - If user asked explicit `Điều X` but all returned docs are fallback (`filter_matched=False`),
     pipeline returns a specific not-found message and exits with `source="legal"`.

5a. Relevance gate
   - `generation.is_retrieval_relevant(effective_query, legal_docs)`
   - If TRUE: stream legal answer and exit with `source="legal"`.
   - If FALSE or no legal docs: continue to web fallback.

6. EPR-scoped web fallback
   - Calls `generation.web_fallback(effective_query)`.
   - Applies EPR domain guard before Tavily call.
   - Returns scoped web answer (or explicit out-of-scope / no-data message) with `source="web_search"`.

### 4.2 Cache Policy Summary

In `optimized_chatbot_pipeline`:
- Chitchat responses:
  - NOT stored in semantic cache
  - still appended to Redis session history
- FAQ/Legal/Web responses:
  - stored in semantic cache after completion

`skip_cache=True` behavior:
- bypasses only the initial semantic cache lookup
- still runs retrieval/generation and stores answers at the end of FAQ/Legal/Web branches

---

## 5. Backend Components (Detailed)

### 5.1 LLM Singletons

File:
- `backend/core/llm_instances.py`

Provides cached singletons via `@lru_cache(maxsize=1)`:
- `get_llm_fast()`:
  - `ChatOpenAI(model="gpt-3.5-turbo", temperature=0)`
  - used for:
    - chitchat responses
    - FAQ answer generation (non-streaming mode)
- `get_llm_router()`:
  - `ChatOpenAI(model="gpt-4o-mini", temperature=0)`
  - used for structured routing and structured outputs
- `get_llm_smart()`:
  - `ChatOpenAI(model="gpt-4o-mini", temperature=0, request_timeout=30)`
  - used for:
    - question rewriting
    - legal generation (non-streaming fallback)
    - relevance gate “judge”
- `get_llm_stream()`:
  - `ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True)`
  - used for streaming answer generation
- `get_embeddings()`:
  - `OpenAIEmbeddings(model="text-embedding-3-small")`

### 5.2 Query Router

File:
- `backend/core/router.py`

Functions:
- `route_query(question)` returns:
  - `"chitchat"` or `"epr_query"`
- Also includes additional router helpers not used by the main pipeline:
  - `route_faq(...)` (legacy alias)
  - `route_law(...)` (law router classification)

Routing method:
- Uses `gpt-4o-mini` via `.with_structured_output(...)` and a Pydantic model with field `datasource`.
- Router prompt defines:
  - `epr_query` for any substantive question (including non-EPR questions, which are later handled by corpus/web fallback)
  - `chitchat` only for pure social interaction (greetings, identity, gibberish)

### 5.3 Question Rewriter

File:
- `backend/core/rewriter.py`

Function:
- `rewrite_question(question, chat_history)`

Behavior:
- If `chat_history` is empty or `"(trống)"`, returns the original question.
- Otherwise:
  - Calls a `gpt-4o-mini` prompt (few-shot) to rewrite the question by resolving ambiguous references (pronouns like “đó/nó/này”, etc.).
- It enforces “don’t change explicit Điều numbers” by prompt rules.

### 5.4 Retrieval (FAQ + Legal)

File:
- `backend/core/retrieval.py`

Key responsibilities:
- Ensure FAQ collection exists in Qdrant on backend startup.
- Treat FAQ as a strict semantic cache (not authoritative legal retrieval path).
- Provide hybrid legal retrieval (dense + lexical + explicit article boost + rerank).
- Provide counting-question shortcut path.

#### FAQ collection setup

Function:
- `ensure_faq_collection()`

When called:
- from `backend/main.py` startup lifespan.

Behavior:
- Uses `get_settings()` to determine:
  - Qdrant mode: cloud vs local
  - collection name: `settings.faq_collection`
  - faq json path: `settings.faq_data_path`
  - embedding model: via `get_embeddings()`
- If the FAQ collection exists and has points_count > 0, it returns.
- Otherwise:
  - loads `data/faq.json` (supports `.get("meta", [])`)
  - for each FAQ item:
    - reads `item["Câu hỏi"]` and `item["Trả lời"]`
    - embeds the question with `embed_query`
    - upserts a Qdrant point with:
      - id: a random UUID string
      - vector: embedding
      - payload: `{"Câu_hỏi": question, "Trả_lời": answer}`

#### FAQ retrieval (strict semantic cache behavior)

Function:
- `retrieve_faq_top1(query, score_threshold=None, keyword_boost=None, rerank=True)`

Async wrapper:
- `retrieve_faq_async(...)`

Behavior:
- Retrieves FAQ candidates by dense similarity, then applies a hybrid score (`semantic + keyword_boost`).
- Computes strict-hit decision via `_is_strict_faq_hit(...)`:
  - minimum semantic/combined score
  - top-1 margin over runner-up
  - query must not look legal-specific (`Điều`, `Khoản`, `Nghị định`, legal obligations keywords, etc.)
- Returns candidate metadata including:
  - `score`, `semantic_score`, `keyword_score`
  - `score_margin`
  - `strict_faq_hit` (boolean)
- Pipeline returns FAQ only when `strict_faq_hit=True`.

#### Law retrieval using hybrid ensemble retriever

Primary runtime retriever:
- `backend/core/ensemble_retrieval.py`
- Public entrypoint: `retrieve_legal_ensemble(query, k=10)`

Current legal retrieval flow:
1. Semantic retrieval:
   - `similarity_search_with_score(...)` on law collection
   - stores `semantic_score` in metadata
2. Lexical retrieval:
   - in-memory BM25-style index built from law payload fields
   - stores `lexical_score` in metadata
3. Explicit article boost:
   - when parser detects explicit `Điều X`, direct lookup by article index
4. Candidate merge + rerank:
   - deterministic fast scorer using overlap/phrase/lead/semantic/lexical features
   - outputs `rerank_score` and `retrieval_debug` breakdown
5. Stage timing:
   - per-query latency breakdown attached in `retrieval_debug["latency_ms"]`
   - includes semantic, lexical, parse, explicit, rerank_merge, total

`backend/core/retrieval.py` wrappers:
- `retrieve_legal(query)` delegates to `retrieve_legal_ensemble(...)`.
- `retrieve_legal_async(query)` runs legal retrieval in thread pool after counting-question check.

Note on legacy code:
- `_FallbackLegalRetriever` still exists in `retrieval.py` for compatibility/reference.
- Main pipeline does not use it for normal legal retrieval path.

#### Token counting path (counting questions)

Functions:
- `is_counting_question(query)`
- `count_articles(query)`:
  - uses structured query constructor and Qdrant filter translation
  - uses Qdrant native `count(...)` API (no full scroll)
- `counting_answer(count_result, query)`:
  - returns a Vietnamese text response including specific “Điều X” list.

Note:
- This path exists in code and is used automatically when the question matches the counting keywords.

### 5.5 Generation (Chitchat + FAQ stream + Legal stream + Web fallback)

File:
- `backend/core/generation.py`

#### Formatting and context assembly
- `format_docs(docs, max_docs=5, max_tokens_per_doc=800)`:
  - builds a single context string for legal generation
  - includes metadata labels:
    - Dieu, Muc, Chuong
  - truncates each doc’s `page_content` by character length approximation.

#### Legal relevance gate

Function:
- `is_retrieval_relevant(question, docs) -> bool`

Behavior:
- Uses gpt-4o-mini structured output with a schema containing:
  - `relevant: bool`
- It constructs a snippet from:
  - metadata labels `Dieu` and `Chuong`
  - plus first 150 chars of `docs[0].page_content`
- It then judges whether the retrieved doc contains answerable information.
- If any exception occurs, it returns `True` (fail-open).

#### Non-streaming legal generation (sync utility)

Function:
- `generate_legal(question: str, docs: List[Document]) -> str`

Behavior:
- If `docs` is empty, returns:
  - `"Xin lỗi, tôi không tìm thấy thông tin liên quan trong cơ sở dữ liệu."`
- Otherwise:
  - builds `context = format_docs(docs)`
  - runs `_legal_gen_prompt | get_llm_smart() | StrOutputParser()`
  - returns a non-streaming text answer.

This function exists in the codebase. The online pipeline currently uses `stream_legal_answer(...)` for streaming responses.

#### Chitchat
- `chitchat_response(question, chat_history)`:
  - uses `_chitchat_prompt` with `get_llm_fast()` (gpt-3.5-turbo)
  - returns non-streaming text.

#### Web fallback (Tavily)

Function:
- `web_fallback(question) -> str`

Behavior:
- First checks `_is_epr_related(question)` via keyword set.
  - If no EPR keyword matches, returns an “out of scope” refusal message.
- Then reads `TAVILY_API_KEY` from environment.
  - If absent or placeholder-like, returns a “not found in internal data” message.
- Uses `langchain_community.tools.tavily_search.TavilySearchResults(k=3)`
  - always scopes search query string with:
    - `EPR tái chế pháp luật Việt Nam Nghị định 08/2022 {question}`
- If results exist, formats a list of titles, URLs, and truncated snippets.
- Adds a warning line instructing user to cross-check with official legal texts.

#### Streaming answer generation

FAQ streaming:
- `stream_faq_answer(user_query, faq_doc)`:
  - builds prompt with:
    - FAQ question/answer and user question
  - streams output using `get_llm_stream()`

Legal streaming:
- `stream_legal_answer(question, docs)`:
  - builds context via `format_docs(docs)`
  - streams via `get_llm_stream()`

---

## 6. Offline Ingestion and Indexing

### 6.1 Building the Law Index into Qdrant

Script:
- `scripts/build_index.py`

Purpose (as implemented):
1. Load `data/law.json` into a list of article dicts
2. For each article, summarize it using `gpt-3.5-turbo` (`get_llm_fast`)
3. Embed the summaries using `text-embedding-3-small`
4. Upsert points into Qdrant collection `settings.law_collection`

Supported law.json format:
- Either:
  - a list of dicts
  - or a dict wrapper containing `{"meta": [...]}`.

Details of summarization:
- `_SUMMARISE_PROMPT` requests “3-4 paragraphs” in Vietnamese.
- Batching:
  - `BATCH_SIZE = 5` articles per LLM batch call.
- If batch summarization fails, it falls back to using raw article texts.

Qdrant upsert:
- Qdrant client selection:
  - Cloud if `use_qdrant_cloud=true` and URL/key provided
  - otherwise local persistent storage at `ROOT / "qdrant_db"`
- Creates `law_collection` if it does not exist:
  - vector size = 1536 (`VECTOR_DIM`)
  - distance = cosine
- Ensures payload indexes for fields:
  - `Dieu`, `Chuong`, `Muc` stored as root-level payload fields
  - uses `PayloadSchemaType.KEYWORD`
- For each article, constructs a payload including:
  - `Dieu`, `Dieu_Name`
  - `Chuong`, `Chuong_Name`
  - `Muc`, `Muc_Name`
  - `Pages`
  - `Text` (raw text)
  - `summary` (the LLM summary)
- Uses point ids:
  - default sequential `point_id = i + j + 1`
  - overridden to integer `dieu` if `Dieu` is int or digit string.

### 6.2 Adding Phụ lục XXII Entries

Script:
- `scripts/add_phuluc_xxii.py`

Behavior:
- Loads `data/law.json`
- Appends a hard-coded list `phuluc_xxii_entries` into `data["meta"]`
- Writes back the modified JSON to `data/law.json` with:
  - `ensure_ascii=False`
  - `indent=2`

### 6.3 Starting Redis Locally

Script:
- `scripts/start_redis.ps1`

Behavior:
- Runs `docker compose up -d redis`
- Pings Redis in the `epr_redis` container
- Provides a hint that `.env` should use:
  - `REDIS_URL=redis://localhost:6379/0`

---

## 7. Storage, Caching, and Chat History

### 7.1 Redis Session Store (Chat History)

File:
- `backend/memory/session_store.py`

Key/value schema:
- Key: `session:{session_id}`
- Value: JSON list of messages:
  - `{"role": "user"|"assistant", "content": str}`

Where this “history” is used:
- The backend uses Redis history to:
  - format chat history for LLM prompts in `backend/core/pipeline.py`
  - drive question rewrite (`backend/core/rewriter.py`) when applicable
  - include history in chitchat prompt context

What is NOT stored here:
- The Streamlit frontend also keeps its own in-memory UI history:
  - `st.session_state.messages`
- The UI history is what the user sees in the browser, but the backend rewrite logic reads history from Redis using the provided `session_id`.

History retention:
- Keeps the most recent:
  - `settings.max_chat_history_exchanges` exchanges
  - which translates to `max_msgs = max_chat_history_exchanges * 2`

TTL:
- After each `append_exchange`, it calls:
  - `await r.expire(_key(session_id), settings.cache_ttl_seconds)`

Important implementation note:
- The same `settings.cache_ttl_seconds` is also used for semantic cache layer exact-match TTL (see semantic_cache).
- Configuration default:
  - `cache_ttl_seconds` in `backend/config.py` is `3600` seconds.

### 7.2 Two-Layer Semantic Cache

File:
- `backend/cache/semantic_cache.py`

Layer 1 (exact):
- Key:
  - `cache:exact:{sha256(normalised_query)}`
- Normalisation:
  - `_normalise`: lower-case + join whitespace
- Value:
  - JSON `{"answer": answer}`
- TTL:
  - `settings.cache_ttl_seconds` seconds in Redis

Layer 2 (semantic):
- Embeds the normalised query via `get_embeddings().embed_query(...)`
- Searches Qdrant collection `settings.cache_collection` using:
  - limit=1
  - `score_threshold=settings.semantic_cache_threshold`
- On cache set:
  - ensures the cache collection exists; if missing, creates it with:
    - vector size 1536
    - cosine distance
  - upserts a point with:
    - id: random UUID string
    - vector: embedding
    - payload: `{"query": normalise(query), "answer": answer}`

Public API:
- `lookup(query)` checks exact then semantic
- `store(query, answer)` stores in both layers

### 7.3 Qdrant Collections Used

Collections created/used in code:
- `faq_collection`
  - created and populated by `ensure_faq_collection()`
- `law_collection`
  - created by `scripts/build_index.py`
- `cache_collection`
  - created on-demand by `semantic_cache._semantic_set()`

Local Qdrant state:
- When running with local Qdrant (i.e., `use_qdrant_cloud=false`), Qdrant persists data on disk under `qdrant_db/` (gitignored).
- At runtime, collections are created/populated by:
  - `ensure_faq_collection()` for FAQ (startup)
  - `scripts/build_index.py` for law
  - `backend/cache/semantic_cache.py` on-demand for the semantic cache collection

---

## 8. Configuration

File:
- `backend/config.py`

Implementation:
- Uses Pydantic Settings loaded from `.env`:
  - `env_file=BASE_DIR / ".env"`
- Missing required values raise a startup error.

Required:
- `openai_api_key` (Field(...))

Key configuration fields:
- Qdrant:
  - `use_qdrant_cloud` (default False)
  - `qdrant_cloud_url`, `qdrant_api_key`
  - `qdrant_local_path` (default `./qdrant_db`)
  - `faq_collection` (default `faq_collection`)
  - `law_collection` (default `law_collection`)
  - `cache_collection` (default `cache_collection`)
- Redis/caching:
  - `redis_url` (default `redis://localhost:6379/0`)
  - `cache_ttl_seconds` (default `3600`)
  - `semantic_cache_threshold` (default `0.95`)
- Pipeline:
  - `faq_score_threshold` (default `0.75`)
  - `faq_keyword_boost` (default `0.3`)
  - `max_retrieval_docs` (default `5`)
  - `max_chat_history_exchanges` (default `3`)

Environment variable propagation:
- `config.py` sets:
  - `os.environ["OPENAI_API_KEY"]`
  - `os.environ["LANGCHAIN_TRACING_V2"]`, `LANGCHAIN_ENDPOINT`, and optional `LANGCHAIN_API_KEY`
  - optional `TAVILY_API_KEY`

---

## 9. Deployment and Infrastructure

### 9.1 Docker Compose

File:
- `docker-compose.yml`

Services:
- `redis`:
  - image `redis:7-alpine`
  - container name `epr_redis`
  - port mapping:
    - `127.0.0.1:6379:6379` (not exposed publicly to LAN)
  - AOF enabled: `--appendonly yes`
  - healthcheck: `redis-cli ping`
- `backend`:
  - built from `Dockerfile.backend`
  - container name `epr_backend`
  - injects `.env` at runtime:
    - `env_file: - .env`
  - sets `REDIS_URL=redis://redis:6379/0` so the backend uses the docker network Redis
  - healthcheck: `curl -f http://localhost:8000/api/v1/health`
  - depends on redis health
- `frontend`:
  - built from `Dockerfile.frontend`
  - container name `epr_frontend`
  - env:
    - `BACKEND_URL=http://backend:8000`
  - depends on backend health
- `nginx`:
  - image `nginx:1.27-alpine`
  - container name `epr_nginx`
  - exposes port `80:80`
  - uses `nginx.conf` as reverse proxy for:
    - `/api/*` and `/docs` to `backend`
    - everything else to `frontend`

### 9.2 Nginx Reverse Proxy for SSE

File:
- `nginx.conf`

Important detail for streaming:
- In `/api/` proxy location:
  - `proxy_buffering off;`
  - `proxy_cache off;`
  - `chunked_transfer_encoding on;`
  - `proxy_read_timeout 120s;`

This is intended to support SSE streaming from FastAPI to the client.

### 9.3 Dockerfiles

Backend:
- `Dockerfile.backend`
  - Base: `python:3.11-slim`
  - Installs `requirements/backend.txt`
  - Copies:
    - `backend/`
    - `data/`
  - Does not copy `.env`
  - Runs:
    - `uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2`

Frontend:
- `Dockerfile.frontend`
  - Base: `python:3.11-slim`
  - Installs `requirements/frontend.txt`
  - Copies `frontend/`
  - Runs:
    - `streamlit run frontend/app.py --server.port=8501 --server.address=0.0.0.0`

---

## 10. Evaluation Harness (Offline Quality Checks)

Files:
- `tests/eval/run_eval.py`
- `tests/eval/evaluators.py`
- `tests/eval/test_cases.json`
- `tests/eval/diagnose.py`
- `tests/eval/compact_stored_results.py` (removes `final_text` and empty judge reason strings from `results_*.json`)
- `tests/eval/results_*.json` (saved outputs; repository may keep compacted snapshots to reduce size)

### 10.1 Test dataset

`tests/eval/test_cases.json` contains:
- `version` and `description`
- a list `cases` where each case includes at least:
  - `id`
  - `query`
  - `category` (e.g., `chitchat`, `faq`, `legal`, `edge`, `web_search`)
  - `expected_route`
  - `expected_keywords`
  - `notes`

### 10.2 Runner

`tests/eval/run_eval.py`:
- Loads test cases
- Filters by `--category` and `--cases`
- Runs `optimized_chatbot_pipeline` for each case with:
  - a unique Redis session id:
    - `eval_{uuid...}`
- Captures:
  - stage timings:
    - computed between `status` events
  - final answer:
    - from `response_complete`
  - source:
    - from `response_complete.source`
  - referenced documents:
    - from `response_complete.documents`

Route inference logic:
- If `"chitchat"` appears in pipeline stages hit:
  - inferred route = `chitchat`
- Else if pipeline hit faq/legal/web stages:
  - inferred route = `vectorstore_faq`
- If source is `cache`:
  - inferred route = `cache_hit`
- Otherwise fallback to `chitchat` (as coded)

Keyword scoring:
- `_check_keywords` checks substring presence for each expected keyword

Optional LLM judge scoring:
- Unless `--no-llm-eval`, it calls:
  - `eval_faithfulness(query, answer, documents)`
  - `eval_relevance(query, answer)`
  - `eval_completeness(query, answer)`
- For faithfulness, judge requires retrieved documents, so runner uses `--no-cache` for faithfulness calls.

### 10.3 LLM judge

`tests/eval/evaluators.py`:
- Defines `EvalScore(score: int [0..5], reasoning: str)`
- Uses `get_llm_smart()` and `.with_structured_output(EvalScore)`
- Implements:
  - faithfulness: checks whether answer claims are supported by provided docs
  - relevance: checks whether answer addresses the question
  - completeness: checks whether answer covers important aspects

### 10.4 Diagnose helper

`tests/eval/diagnose.py`:
- Loads `tests/eval/results_e2e.json` (works with compacted files; they omit `final_text`)
- Prints:
  - cases where `source == cache`
  - keyword misses where `missing_keywords` and category != `chitchat`
  - warnings for legal keyword_hit_rate < 0.5 or errors

---

## 11. Requirements

Backend dependencies:
- `requirements/backend.txt`
  - fastapi, uvicorn, sse-starlette
  - langchain, langchain-core, langchain-openai, langchain-qdrant
  - qdrant-client
  - openai
  - tavily-python
  - redis, python-dotenv, tiktoken, tqdm, etc.

Frontend dependencies:
- `requirements/frontend.txt`
  - streamlit, httpx
  - fpdf2 (PDF export)

---

## 12. Summary of System Data Flow

1. User submits a question from Streamlit.
2. Streamlit calls `POST /api/v1/chat` and reads SSE events.
3. Backend pipeline:
   - loads Redis session history
   - attempts semantic cache lookup
   - routes chitchat vs retrieval
   - optionally rewrites question based on history
   - retrieves FAQ first; if hit, streams FAQ answer
   - if FAQ strict-hit fails, retrieves legal docs via hybrid ensemble (dense + lexical + rerank)
   - runs an LLM-based relevance gate (fail-open)
   - if legal docs fail or are irrelevant, uses Tavily web fallback (EPR-scoped)
4. Backend appends the final assistant message to Redis session history and caches substantive answers.
5. Frontend displays the streaming response and (when present) cited document metadata.

---

## 13. File-Level Map (Quick Reference)

- `README.md`: project description, architecture diagram, setup and eval notes.
- `backend/main.py`: FastAPI app + lifespan startup (Redis ping, FAQ collection ensure).
- `backend/config.py`: Pydantic settings; env var wiring; Qdrant/Redis/pipeline configuration.
- `backend/api/schemas.py`: request/response models (`ChatRequest`, `HealthResponse`).
- `backend/api/routes/chat.py`: SSE endpoint `/api/v1/chat` streaming pipeline events.
- `backend/api/routes/health.py`: `/api/v1/health` checks Qdrant and Redis.
- `backend/core/pipeline.py`: `optimized_chatbot_pipeline` orchestrating cache/routing/rewrite/retrieval/generation/web fallback.
- `backend/core/router.py`: LLM route classification (`chitchat` vs `epr_query`) with structured output.
- `backend/core/rewriter.py`: question rewriting using chat history (pronoun resolution).
- `backend/core/retrieval.py`: FAQ indexing/retrieval and legal retrieval wrappers (ensemble + counting path).
- `backend/core/generation.py`: chitchat, FAQ/Legal streaming generation, relevance gate, and Tavily web fallback.
- `backend/core/llm_instances.py`: cached LLM and embeddings instances.
- `backend/cache/semantic_cache.py`: two-layer semantic cache (Redis exact + Qdrant semantic).
- `backend/memory/session_store.py`: Redis-backed session history with TTL and exchange trimming.
- `frontend/app.py`: Streamlit UI, SSE parsing, display, PDF export.
- `scripts/build_index.py`: offline law summarization, embedding, Qdrant upsert and payload indexes.
- `scripts/add_phuluc_xxii.py`: append hard-coded Phụ lục XXII entries into `data/law.json`.
- `scripts/eda_law.py`: EDA on `data/law.json` length/token distributions (useful for chunking decisions).
- `scripts/start_redis.ps1`: local redis start via docker compose.
- `tests/eval/run_eval.py`: evaluation runner calling the pipeline and scoring.
- `tests/eval/compact_stored_results.py`: shrink committed `results_*.json` (drops `final_text`, empty judge reasons).
- `tests/eval/evaluators.py`: LLM-as-judge scoring functions.
- `tests/eval/test_cases.json`: golden test dataset.
- `tests/eval/diagnose.py`: prints diagnostic summaries from previous eval results.
- `docker-compose.yml`: orchestrates redis/backend/frontend/nginx.
- `nginx.conf`: reverse proxy configuration for SSE streaming.
- `Dockerfile.backend`, `Dockerfile.frontend`: container build recipes.
- `requirements/backend.txt`, `requirements/frontend.txt`: dependency pins.

