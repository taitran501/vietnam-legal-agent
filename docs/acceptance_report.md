# Refactor acceptance record

Validation date: 2026-08-10. Local environment: Windows, Python 3.11.9,
Node.js 20-compatible toolchain, Docker Desktop, local OpenAI-backed generation,
and file-backed Qdrant collections.

## Frozen baseline

- Legacy import commit: `8f5deae` (`chore: import legacy EPR chatbot baseline`).
- Baseline tag: `legacy-v1.0.0`.
- Historical legacy test snapshot: 161 passed, 1 skipped.
- Golden lookup dataset: `tests/eval/test_cases.json` with 33 cases.
- Source corpus: 49 FAQ entries and 178 legal records.

## Product acceptance

- The existing `POST /api/v1/chat` request fields and SSE events remain
  compatible. `workflow_step` is additive.
- One closed LangGraph workflow supports legal lookup, preliminary EPR
  assessment, compliance checklist generation, and bounded chitchat.
- An assessment or checklist with any required case fact missing terminates as
  `awaiting_user_input`; web search cannot fill company facts.
- Claim-level citation verification blocks unsupported legal output and permits
  at most one repair.
- A run permits at most three retrieval actions and records its trace id, action
  sequence, tool latency, and termination reason.
- SQLAlchemy/Alembic owns users, conversations, messages, summaries, active
  cases, and agent runs. PostgreSQL is the deployment source of truth and
  SQLite uses the same schema locally.
- The React workspace implements the reviewed Stitch states: expanded and
  collapsed history navigation, responsive mobile/tablet layouts, real workflow
  progress, clarification and safe-stop states, case facts, source drawer,
  assessment, and checklist output.

## Local verification

- Python suite: 233 passed, 1 skipped (234 collected).
- Mypy: success for all 22 files in `src/epr_agent`.
- Scoped Ruff checks: passed for the bounded workflow, API, retrieval tooling,
  trajectories, and new regression files.
- Alembic: upgraded a fresh SQLite database successfully.
- React Vitest: 3 files, 5 tests passed.
- Playwright: 9 of 9 browser tests passed, including real FastAPI + LangGraph +
  SSE lookup and multi-turn case-resume flows.
- React lint and production build: passed. Vite reports only a non-blocking
  bundle-size warning (about 1.07 MB before gzip, 366 KB gzip).
- Docker: backend and frontend images built successfully; the full React,
  FastAPI, PostgreSQL, Redis, Qdrant, and Nginx stack became healthy; `/` and
  `/api/v1/health` returned HTTP 200.

## Retrieval evidence

| Collection | Points | P@1 | NDCG@3 | Recall@5 | Explicit article hit@3 | Audit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `law_collection_baseline_v1` | 461 | 0.9375 | 0.9375 | 0.9375 | 1.0 | Passed |
| `law_collection_legal_structure_v2` | 1,989 | 0.9375 | 0.9375 | 0.9375 | 1.0 | Passed |

Both rows use the same 16-query live dense + BM25-style + heuristic-rerank
protocol. The structure-aware candidate also passed schema, hygiene, duplicate,
legal-anchor, source-metadata, and deterministic offline gates. It is marked
`promotable: true`; the baseline remains available for rollback.

The 33-case golden runner now supports `--isolated-state`, which removes
history/cache side effects while keeping live routing, retrieval, and generation.
This prevents Redis or an old SQLite history file from contaminating a release
comparison. LLM-as-judge and Tavily are intentionally disabled in this snapshot.
Run those variable-cost checks manually only when a release candidate needs them.

The final isolated live snapshot passed its configured release gate: 33/33
routes correct, 84.03% average keyword hit rate, 10.106 s p95 latency, and no
pipeline errors. The gate used routing >= 90%, keyword hit >= 80%, and p95 <=
15 s. Generated answers remain model-dependent, so this snapshot is reported
separately from deterministic local tests.

## Deployment boundary

No remaining code path is required for the scoped V1 implementation. A real
deployment must still provide production secrets, run Alembic against
PostgreSQL, publish the approved candidate collection (or explicitly keep the
baseline), set the matching `CORPUS_VERSION`, and run the gated live evaluation.
Those are release operations, not local artifacts committed to Git.
