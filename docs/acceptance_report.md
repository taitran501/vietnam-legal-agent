# Refactor acceptance report

Environment: Python 3.11.9, Windows local development.

## Frozen legacy baseline

- Commit: `8f5deae` (`chore: import legacy EPR chatbot baseline`)
- Tag: `legacy-v1.0.0`
- Baseline test run before the refactor: `161 passed, 1 skipped`
- The 33-case golden manifest remains at `tests/eval/test_cases.json`.

## Refactor branch

- Full test suite: `192 passed, 1 skipped`
- New bounded-workflow tests: 30 passed
- Trajectory coverage: 12 cases
- Ruff: passed for `src/epr_agent` and new tests
- Mypy: passed for `src/epr_agent`
- Python compile check: passed for `backend` and `src`
- React TypeScript/Vite build: passed
- `git diff --check`: passed; Git only reports Windows LF/CRLF conversion warnings

The live Qdrant, Redis, Tavily and OpenAI end-to-end golden evaluation was not
run as part of this local acceptance command. The legacy pipeline remains
available for that evaluation, while new workflow tests use injected adapters
so they do not spend external API calls or depend on local services.
