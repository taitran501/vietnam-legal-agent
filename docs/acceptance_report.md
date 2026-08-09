# Refactor validation record

Date: 2026-08-10. Environment: Windows local development, Python 3.11.9 and
Node.js local toolchain.

## Frozen baseline

- Legacy import commit: `8f5deae` (`chore: import legacy EPR chatbot baseline`)
- Baseline tag: `legacy-v1.0.0`
- Historical baseline run: `161 passed, 1 skipped`
- Golden legal-lookup cases: `tests/eval/test_cases.json` (33 cases)

## Checks completed for this refactor

- Python compile check passed for `src/epr_agent` and `backend`.
- Focused persistence, workflow, SSE, session/case API, structural chunking,
  retrieval-manifest, and 12 deterministic trajectory tests: **36 passed**.
- Scoped Ruff check passed for the new/changed bounded-workflow, persistence,
  session API, retrieval scripts, and related tests.
- Alembic upgrade passed against a new temporary SQLite database.
- `docker compose config --quiet` passed for React, FastAPI, PostgreSQL, Redis,
  Qdrant, Nginx, and the optional legacy Streamlit profile.
- React Vitest: **3 passed**.
- React Playwright trajectories: **2 passed** (missing-facts stop and
  no-evidence safe stop).
- React ESLint completed with **0 errors** and 7 existing warnings in legacy
  Toast/Markdown modules; the new compliance-workflow UI files have no lint
  findings.
- React production build passed. Vite reports a non-blocking large-chunk
  warning (about 1.06 MB before gzip).
- The source manifest confirms 49 FAQ records and 178 legal records. No live
  retrieval score is claimed until a named Qdrant collection is evaluated.

## Checks still required before release

- The complete Python suite did not collect in the current global interpreter:
  it has LangChain 1.3.14 while the project locks LangChain 0.3.7, so the
  legacy import `langchain.chains` is unavailable. This is an environment
  dependency mismatch, not a failing refactor assertion.
- A clean temporary virtual environment was created, but package installation
  was blocked by the configured package registry failing to provide the required
  `numpy<2` distribution. Re-run `python -m pip install -e ".[dev]"` in a clean
  environment with a working package index, then run `pytest -q` and
  `mypy src/epr_agent`.
- Build and exercise the actual Compose containers; only Compose syntax and the
  Alembic migration were verified locally.
- Run the 33 golden cases and live retrieval benchmark against a configured
  Qdrant/OpenAI environment. Promote the structure-aware collection only if the
  gates in `docs/retrieval/README.md` pass.
- Attach an approved Stitch export URL and desktop/mobile screenshots in
  `docs/design/` before claiming design approval.
