# EPR Compliance Copilot

[![CI](https://github.com/taitran501/legal_epr/actions/workflows/ci.yml/badge.svg)](https://github.com/taitran501/legal_epr/actions/workflows/ci.yml)

EPR Compliance Copilot is a Vietnamese-language application that helps
businesses understand and prepare for Extended Producer Responsibility (EPR)
requirements in Vietnam.

Users can ask about a legal provision, explain a situation, prepare a
compliance checklist, and inspect the official sources behind an answer. The
application is intentionally focused on Vietnamese EPR law and returns a
preliminary, source-grounded result rather than pretending to replace a
lawyer or an official legal opinion.

## Thử nhanh

Nếu bạn chỉ muốn trải nghiệm sản phẩm, hãy chạy local preview theo
[runbook local preview](docs/runbooks/local-preview.md). Không cần biết route
hay pipeline: mở màn hình chào mừng, chọn một trong ba việc **Tra cứu quy
định**, **Kiểm tra trường hợp của doanh nghiệp**, hoặc **Tạo danh sách việc cần
làm**, rồi làm theo các câu hỏi được hiển thị.

Repository hiện chưa có hosted demo công khai. Các acceptance report và số liệu
kiểm thử local không phải là URL production hay bằng chứng rằng corpus đã được
phê duyệt pháp lý.

### Sản phẩm hiện hỗ trợ

| Bạn muốn làm gì? | Kết quả |
| --- | --- |
| Tra cứu một điều khoản EPR | Câu trả lời có căn cứ và source drawer để đối chiếu |
| Kiểm tra trường hợp doanh nghiệp | Thu thập đúng các dữ kiện còn thiếu và trả về đánh giá sơ bộ |
| Lập checklist tuân thủ | Danh sách việc cần làm gắn với căn cứ |
| Không đủ căn cứ hoặc corpus chưa sẵn sàng | Dừng an toàn, nêu lý do và không tự thay bằng điều khoản gần giống |

Kết quả luôn là thông tin sơ bộ. Người dùng cần đối chiếu văn bản chính thức
và quy trình phê duyệt nội bộ trước khi ra quyết định quan trọng.

## What you can do

- Ask questions about EPR provisions, including Articles 77–86.
- Open citations in a source drawer with the document, article, excerpt, and
  corpus status.
- Assess a company situation by filling in the facts the workflow actually
  needs.
- Prepare an evidence-linked compliance checklist.
- Continue a case after answering a follow-up question.
- Stop a response, retry it, or regenerate it without losing the previous
  answer.
- Save conversations, rate answers, and reload them later.
- Explicitly search approved official websites when web research is needed.

## Usage

After starting the application, the web client exposes the following
workflows:

- **Legal lookup**: submit a provision or question and inspect the streamed
  answer with its source citations.
- **Case assessment**: open **Thông tin tình huống**, complete the required
  case facts, and select **Lưu và tiếp tục đánh giá**.
- **Compliance checklist**: select the checklist task, complete the required
  facts, and select **Lưu và tiếp tục lập checklist**.
- **Follow-up**: continue in the same conversation; the active case context is
  loaded before the next turn is routed.
- **Recovery**: stop an in-progress turn, retry a failed turn, or regenerate a
  persisted assistant message without duplicating the user message.

Required case fields are supplied by the backend case schema and validated in
the case panel. Missing facts result in an explicit follow-up request. If an
article is not supported by the active corpus, the application returns a
safe-stop result instead of substituting a nearby provision.

## Scope and trust model

The current application covers Vietnamese EPR law. It is designed around a
few important rules:

- Answers should be supported by an active legal source and show citations.
- User-entered facts are labelled as user-provided; they are not treated as
  independently verified documents.
- A missing provision, weak evidence, incomplete case, stale corpus, or
  unavailable dependency produces a reason-specific safe stop.
- Web research is an explicit action, not a silent fallback. Web evidence is
  restricted to configured official domains such as `vanban.chinhphu.vn` and
  `vbpl.vn`.
- The corpus contains the 2022 EPR decree and the amendment instruments
  currently tracked by the repository. Legal approval and the corpus-as-of
  date remain an external production release decision.

When `CORPUS_RUNTIME_MODE=preview`, local or staging users can exercise the
workflow with a persistent preview warning. Production defaults to
`production` and blocks legal answers until the corpus passes the technical
checks and the legal approval gate.

> This application provides preliminary, source-grounded information. It is
> not legal advice and should not be the only basis for an important business
> or compliance decision.

## Run the application locally

### Prerequisites

- Python 3.11
- Node.js 18 or newer
- Docker Desktop and Docker Compose for the full stack
- An OpenAI API key for live answer generation

### Option 1: full Docker stack

This is the recommended path when you want the frontend, API, persistence,
cache, vector search, and indexer together.

```powershell
git clone https://github.com/taitran501/legal_epr.git
Set-Location legal_epr

Copy-Item .env.example .env
# Edit .env and set OPENAI_API_KEY.
# For local/staging validation, set CORPUS_RUNTIME_MODE=preview.

docker compose up -d --build
docker compose ps -a
Invoke-RestMethod http://127.0.0.1/api/v1/ready
```

Open the application at [http://127.0.0.1](http://127.0.0.1).

The Compose stack contains:

| Service | Purpose |
| --- | --- |
| `nginx` | Public entry point on port 80 and SSE proxy |
| `frontend` | React application |
| `backend` | FastAPI API and agent workflow |
| `postgres` | Durable production-style storage |
| `redis` | Cache, rate limiting, and short-lived context |
| `qdrant` | Legal vector collection |
| `indexer` | One-shot corpus audit and index build |

Useful commands:

```powershell
docker compose logs -f backend indexer
docker compose ps -a
docker compose down
```

Keep `CORPUS_RUNTIME_MODE=preview` for local testing while the corpus approval
field is pending. Do not use preview mode as a production bypass.

### Option 2: run the API and frontend separately

Create a Python environment and install the backend:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, install and start the React application:

```powershell
Set-Location frontend-react
npm.cmd install
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8000"
npm.cmd run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). Vite proxies `/api` to
the backend. When `DATABASE_URL` is unset, local development uses the SQLite
history database configured by `HISTORY_DB_PATH`; PostgreSQL is used by the
Compose deployment.

## Configuration

Copy `.env.example` to `.env` and configure only the services you use. Never
commit `.env`, database files, Qdrant storage, logs, or generated evaluation
reports.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for live answer and embedding generation |
| `CORPUS_RUNTIME_MODE` | `production` or `preview`; defaults to `production` |
| `DATABASE_URL` | PostgreSQL URL; unset uses local SQLite |
| `HISTORY_DB_PATH` | SQLite history path when PostgreSQL is not configured |
| `QDRANT_URL` | Self-hosted Qdrant endpoint |
| `USE_QDRANT_CLOUD` | Use Qdrant Cloud when set to `true` |
| `REDIS_URL` | Redis endpoint for cache and rate limiting |
| `RATE_LIMIT_FAIL_OPEN` | Explicit local-preview override; keep `false` in production |
| `TAVILY_API_KEY` | Optional provider for explicit official-web research |
| `OIDC_ISSUER` | OIDC discovery issuer for deployed browser authentication |
| `OIDC_AUDIENCE` | Expected JWT audience |
| `OIDC_CLIENT_ID` | React OIDC client ID |
| `OIDC_REQUIRED_GROUP` | Optional internal-access group or role |
| `REQUIRE_AUTH` | Keep enabled for deployed environments |

Browser users authenticate through OIDC in a deployed environment. Non-browser
automation uses `X-Service-Token` with configured scopes. Access tokens are not
used as conversation ownership keys and are not persisted by the application.

For a local deterministic browser test only, authentication can be disabled in
the isolated test configuration. Do not expose that mode on a shared or
internet-facing server.

## API

The interactive API documentation is available at
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) when the backend is
running.

Common endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Process liveness |
| `GET` | `/api/v1/ready` | Dependency and capability readiness |
| `GET` | `/api/v1/me` | Current authenticated identity and roles |
| `POST` | `/api/v1/chat` | Stream a question or case turn over SSE |
| `PUT` | `/api/v1/conversations/{id}/turns/{turn_id}/cancel` | Cancel a running turn |
| `GET` | `/api/v1/sessions` | List owned conversations |
| `GET` | `/api/v1/sessions/{id}` | Load a conversation |
| `GET/PATCH` | `/api/v1/sessions/{id}/case` | Read or save case facts |
| `PUT` | `/api/v1/conversations/{id}/messages/{message_id}/feedback` | Save feedback |

`POST /api/v1/chat` supports `message`, `continue_case`, `retry`, and
`regenerate` operations. A turn has a durable status such as `streaming`,
`complete`, `stopped`, or `failed`, so a reload does not turn an interrupted
response into a false completed answer.

## Project structure

```text
backend/              FastAPI application, authentication, routes, persistence
src/epr_agent/        Agent domain, workflow, retrieval, evidence, and tracing
frontend-react/       React UI, SSE client, case panels, and browser tests
scripts/              Corpus synchronization, migrations, indexing, and audits
data/                 Legal corpus, rule pack, manifests, and fixtures
docs/                 Runbooks, acceptance reports, and design documentation
tests/                Unit, contract, integration, evaluation, and API tests
```

At a high level, a request moves through:

```text
React UI → FastAPI/SSE → bounded workflow → retrieval/evidence checks
         → structured answer → durable persistence → source-aware UI
```

The workflow has declared routes for legal lookup, explanation/comparison,
case assessment, checklist preparation, explicit web research, chitchat, and
out-of-scope requests. Retrieval uses structure-aware legal chunks, explicit
article anchors, dense search, lexical search, and evidence validation before
generation.

## Testing and development checks

Backend checks:

```powershell
python -m scripts.sync_corpus_metadata --check
python -m pytest -q
ruff check src/epr_agent backend scripts tests
mypy src/epr_agent backend
python -m tests.eval.run_eval --suite all --output data/eval/v4-deterministic.json
```

Frontend checks:

```powershell
Set-Location frontend-react
npm.cmd run test
npm.cmd run build
npm.cmd run test:e2e
```

The browser suite covers desktop, tablet, and mobile layouts; direct URLs and
browser history; streaming and cancellation; source citations; case save and
continuation; feedback reload; retries; safe stops; preview/production
readiness; and official-web filtering.

## Operations and troubleshooting

### `/api/v1/ready` returns `503`

Inspect the `capabilities` and `corpus` fields in the response. Common reasons
are:

- `database_schema_mismatch`: run the migration procedure in
  [`docs/runbooks/database-migration.md`](docs/runbooks/database-migration.md).
- `corpus_promotion_blocked`: production approval or corpus metadata is still
  missing.
- `corpus_index_mismatch`: the active Qdrant collection does not match the
  manifest hash or index contract.
- `provider_not_configured`: the optional web provider is not configured.

### History works but legal chat is unavailable

This is expected when history is ready but the legal corpus or one of its
dependencies is not. In preview mode the UI shows a persistent warning; in
production legal chat remains disabled until the promotion gate passes.

### Web research is unavailable

Set `TAVILY_API_KEY` only when explicit web research is part of the deployment.
Results are accepted only when they pass the official-domain and relevance
checks. Web research is never used silently to fill missing company facts.

### Operational runbooks

- [Local preview](docs/runbooks/local-preview.md)
- [Current acceptance status](docs/acceptance_status.md)
- [External release gates](docs/runbooks/external-release-gates.md)
- [Database and owner migration](docs/runbooks/database-migration.md)
- [Production corpus promotion](docs/runbooks/production-promotion.md)
- [Rollback](docs/runbooks/rollback.md)
- [Browser acceptance report](docs/browser_acceptance_report.md)

## Current limitations

The application currently focuses on Vietnamese EPR law. The following are
outside the current product scope:

- document upload and OCR;
- export to a formal legal or compliance report (only a preliminary text export is supported);
- historical-law date selection;
- long-term user profile memory;
- broad web search outside the configured official domains;
- additional legal domains beyond EPR.

## License

MIT
