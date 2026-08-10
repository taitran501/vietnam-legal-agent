# EPR Compliance Copilot

EPR Compliance Copilot is a Vietnamese legal-compliance assistant for Extended
Producer Responsibility (EPR). It uses a **bounded agentic workflow**: the
system can select only declared routes and never discovers tools or loops on
its own.

> It provides document-grounded information, not legal advice.

## Pipeline versions

```text
official legal source
  -> canonical LegalDocument / LegalChunk audit
  -> structure-aware chunking (Điều -> Khoản -> Điểm)
  -> fixed embedding profile + versioned Qdrant collection
  -> QueryPlan (understanding and follow-up rewrite)
  -> route-specific workflow
  -> dense + BM25-style retrieval -> RRF -> heuristic rerank
  -> evidence gate -> answer composition
  -> structural + claim-support citation verification
  -> persist run, trace, conversation, and active case
```

The only indexed corpus is EPR. The corpus abstraction and route contracts
are reusable for another legal domain, but no other domain is silently searched.

Pipeline V4 is now the default runtime. It
replaces generic case-answer generation with issue-oriented EPR assessment and
checklist workflows: a quick action only prefills the composer, facts retain
their user/panel provenance, evidence is checked per legal issue, and a result
card is rendered only after the deterministic case decision completes.  The
official Appendix XXII table must be extracted and audited before V4 can build
or activate its versioned index. The previous V3 collection and Git tag are
retained as rollback artifacts. See
[`docs/pipeline_v4_behavior_contract.md`](docs/pipeline_v4_behavior_contract.md).

## Route contracts

| Route | Behaviour | Cache |
| --- | --- | --- |
| `legal_lookup` | Direct law lookup, up to 3 evidence chunks | Only a standalone, verified legal answer |
| `legal_explain_compare` | Explain or compare provisions, up to 6 evidence chunks | Never |
| `case_assessment` | Collect explicit EPR facts before a preliminary assessment | Never |
| `compliance_checklist` | Collect facts, then create an evidence-linked checklist | Never |
| `research_web` | Explicit public-web research selected by the user | Never |
| `chitchat` | Greeting or small talk without retrieval | Never |
| `out_of_scope` | Safe stop outside the registered corpus | Never |

The only reusable answer is a verified standalone `legal_lookup`, stored under
an exact Redis key containing its normalized-query digest, route, corpus SHA,
and embedding profile. V3 never uses semantic answer-cache matching: similar
questions about different Articles must run their own legal retrieval.

For an EPR assessment or checklist, V4 validates the facts required by each
legal issue. These can include the business role, object/product group,
material or packaging specification, market placement, purpose, exemptions,
revenue thresholds, reuse, and effective date. Missing decision facts produce
`needs_information`; web research never fills in company facts.

When legal evidence is insufficient, the answer stops safely and offers the
user the explicit action **“Tìm nguồn công khai”**. It does not automatically
fall through to web search.

## Legal corpus and retrieval

`data/corpus_manifest.json` declares the EPR source document. The canonical
builder accepts only source-traceable records, gives every chunk a stable ID,
and audits provenance, duplicate IDs, anchors, source offsets, and malformed
text before indexing. Untraceable manual Appendix records are excluded from
the production index but remain in the raw extraction for review.

The fixed embedding contract is:

- profile: `openai-text-embedding-3-small-v1`
- model: `text-embedding-3-small`
- dimensions: `1536`
- deterministic NFC/whitespace normalization for both documents and queries

Each Qdrant collection is versioned by corpus SHA, index schema, chunking
profile, and embedding profile. The one-shot indexer audits a new collection
and only then switches the `law_collection` alias; older collections stay
available for rollback. Readiness fails when the active collection's corpus or
embedding metadata does not match the runtime contract.

Legal retrieval performs exact metadata lookup for explicit anchors, dense
top-20 and BM25-style top-20 in parallel, reciprocal-rank fusion (`k=60`),
chunk-ID deduplication, and a heuristic rerank to 10 candidates. A route then
selects its evidence limit. An explicit named Article must rank first; if it is
absent, the system stops rather than substituting a nearby Article. The
cross-encoder remains shadow-only.

`data/faq.json` is retained only for UI examples and evaluation. It is not
indexed, retrieved, cited, or used as runtime evidence.

## Safety, trace, persistence, and API

Evidence must include a legal anchor, source provenance, corpus version/SHA,
embedding profile, and stable document ID. Citation verification has two
layers: structural validation, then one structured LLM batch checking whether
the legal claims are supported by their cited chunks. At most one repair is
allowed. No supported legal claim means no `answer_complete`.

PostgreSQL is the production source of truth for users, conversations,
messages, summaries, active cases, runs, and trace events. SQLite uses the
same SQLAlchemy/Alembic schema locally. Redis is used only for cache, hot
context, rate limiting, and short-lived feedback. The API-key hash scopes
stored data to its owner.

`POST /api/v1/chat` continues to accept `query`, `conversation_id`, and legacy
`session_id`. It also accepts optional `mode: "auto" | "research_web"`.
Existing SSE events remain compatible; `response_complete` adds route, corpus,
embedding, evidence-status, available-action, and termination metadata.

The React client consumes this `POST` stream with `fetch` and a
`ReadableStream` so it can send the API key header and cancel a running request.
It renders `status` and `workflow_step` events while the workflow runs. Legal
answer chunks are emitted progressively only after citation verification has
passed; this prevents an unverified legal claim from appearing in the UI. The
API sends keepalive pings and no-transform headers, and Nginx disables proxy
buffering for `/api/`.

`GET /api/v1/health` is process liveness. `GET /api/v1/ready` checks database,
Redis, Qdrant, OpenAI configuration, collection alias, point count, corpus
SHA, schema, and embedding profile. It returns `503` while the legal corpus is
not ready. With `ENABLE_TRACE_DEBUG_API=true`, owner-scoped trace inspection is
available at `/api/v1/debug/traces/{trace_id}`. The React trace drawer is built
only with `VITE_ENABLE_TRACE_DEBUG=true` and never displays raw prompts or chat
history.

## Local development

Requirements: Python 3.11, Node.js 18+, Docker Desktop, and an `.env` with the
required OpenAI configuration. Do not commit `.env`, database files, Qdrant
storage, logs, or cache artifacts.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

Set-Location frontend-react
npm install
npm run dev
```

For the complete local stack:

```powershell
docker compose up --build
```

Compose starts PostgreSQL, Redis, Qdrant 1.12.1, a one-shot law indexer,
FastAPI, React, and Nginx. The backend waits for the indexer to complete
successfully before starting.

## Verification

This repository intentionally has no CI/CD workflow. The complete local test
matrix and the distinction between deterministic and real-service checks are
documented in [`docs/v4_test_matrix.md`](docs/v4_test_matrix.md). The fast
deterministic checks are:

```powershell
.venv_acceptance\Scripts\python.exe -m pytest -q
.venv_acceptance\Scripts\ruff.exe check src/epr_agent backend scripts tests
.venv_acceptance\Scripts\mypy.exe src/epr_agent

python -m tests.eval.run_eval --suite all --output data/eval/v4-deterministic.json

Set-Location frontend-react
npm.cmd run test
npm.cmd run build
npm.cmd run test:e2e -- --grep-invert "real FastAPI|real multi-turn"
```

The real-stack checks require Docker Compose and are run explicitly; they are
not part of the fast unit command. The OpenAI live suite is also opt-in and
writes a timestamped report, so deterministic doubles are never presented as
live quality measurements.

## Design handoff

The reviewed Stitch export is preserved as
[`stitch_legal_assistant_system.zip`](docs/design/stitch_legal_assistant_system.zip).
The product UI is Vietnamese; repository documentation is English.

## License

MIT
