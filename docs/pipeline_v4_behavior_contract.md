# Pipeline V4 behavior contract

Pipeline V4 is a server-selected, bounded workflow for EPR case assessment
and compliance checklists. It is the default runtime; the browser cannot
select a runtime. Operators can temporarily roll back with
`AGENT_PIPELINE_VERSION=pipeline-v3`.

## Turn contract

`POST /api/v1/chat` keeps the legacy `query`, `conversation_id`, `session_id`,
and `mode` fields.  V4 adds optional `operation`, `intent_hint`,
`interaction_source`, and `case_patch` fields. `interaction_source=guided_form`
identifies the inline assessment/checklist form. The legal-lookup quick action
still writes an editable draft; assessment and checklist actions open the form
without inventing a company profile or creating a turn.

For an assessment or checklist, the workflow is:

While editing, `POST /api/v1/case-form/resolve` computes visible fields,
validation errors and dynamic counts without persistence. A guided submit then
uses one durable chat turn:

```text
validate -> load conversation/case -> understand intent -> resolve and merge typed facts
-> return the full form state OR retrieve evidence per legal issue
-> coverage gate -> deterministic decision -> citation verification -> persist
```

An assessment cannot show a result card before all required facts and issues
are covered. Missing facts yield `needs_information` and a guided card that
names the number of missing items; the runtime does not ask only for the first
missing key. Incomplete legal coverage yields `insufficient_evidence`. Neither
state is an answer-complete assessment. Web research is a user-selected action
and never infers a company fact. PATCH case remains the compatibility/full
editor path, not a required step before a guided submit.

## Appendix XXII evidence

The historical short Appendix summaries remain excluded.  The V4 indexer runs
`scripts.extract_appendix_xxii` to convert the authoritative DOC through
LibreOffice and extract PDF table rows with source hash, page, table ID, row
ID, cell text, and bounding box.  The extractor fails closed.  With V4
enabled, a missing or invalid extracted file prevents index alias promotion.

The generated file belongs under `artifacts/appendix_xxii.jsonl`, shared by
the one-shot indexer and backend Compose services.  It is deliberately ignored
by Git; the source DOC and extraction code are the reproducible inputs. The
corpus identity canonicalizes the JSONL rows and ignores only the
converter-specific `PDF_SHA256` field, which can differ between LibreOffice
versions. `data/corpus_manifest.json` records the resulting Appendix digest;
the indexer still requires and validates the actual runtime artifact before
promoting an alias.

## Local checks

Use the project virtual environment for backend checks and run the frontend
tests outside restrictive filesystem sandboxes when required by Vite/esbuild.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/agent tests/tools
Set-Location frontend-react
npm run test
npm run build
```

Live retrieval metrics, the Appendix extraction audit, Docker smoke test, and
full Playwright trajectories are separate acceptance evidence.  Do not claim
those gates pass until the real local services and official source conversion
have completed.
