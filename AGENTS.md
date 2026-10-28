# Repository instructions

## Product and runtime

This repository contains the Vietnam Legal Agent application and a separately packageable legal-source-verifier skill. The application entry point is `backend.main:app`; `Dockerfile.backend` and the Compose files define the supported runtime. The React client lives in `frontend-react/`, and application code lives in `backend/` and `src/vietnam_legal_agent/`.

Do not reintroduce the retired Gradio/Hugging Face Space runtime. Keep `nginx.conf`, which is used by the Compose gateway. Treat API schemas and persisted data formats as compatibility contracts; change them only when the task requires it and update the matching contracts and tests.

## Legal evidence and engineering

- Ground legal answers in source text that has been retrieved and checked. Never invent an authority, instrument number, provision, quotation, effective date, or citation.
- Keep facts supplied by a user distinct from facts confirmed by an authoritative source. State what remains unknown and ask a focused follow-up when a missing fact changes the answer.
- For current-law questions, verify the instrument and amendments on an official source, confirm the relevant effective dates and transition clauses, and make the answer's as-of date clear. If the available evidence is incomplete or conflicting, explain the gap and stop short of a firm conclusion.
- Deterministic rules are appropriate for explicit, documented contracts such as input validation, security controls, source/citation format checks, and fail-closed behavior. Legal decision rules need a traceable legal basis, a narrow scope, tests, and a documented rationale. Do not add broad keyword mappings or query-specific heuristics as substitutes for source verification; demonstrate a measured retrieval or safety improvement before introducing them.
- Preserve the distinction between engineering evaluation fixtures and legal ground truth. A passing test suite does not establish legal correctness or production approval.

See `.agents/skills/legal-evidence-engineering/SKILL.md` for the repository-specific review checklist. The portable workflow is in `skills/vietnam-legal-source-verifier/SKILL.md`.

## Validation

Use the repository's Python 3.11 environment. The principal local checks are:

```bash
python -m pip install -e ".[dev]"
ruff check src/vietnam_legal_agent backend scripts tests
mypy src/vietnam_legal_agent backend
python -m pytest -q
python -m tests.eval.run_eval --suite all
python tests/eval/agent_harness.py --suite all
python tests/eval/persona_simulation.py --persona all
```

Frontend checks run from `frontend-react/` with `npm ci`, `npm run lint`, `npm run test`, and `npm run build`. See the CI workflow for browser, load, and Compose checks. Live provider-backed evaluation is a separate manual workflow and must not be described as a CI result.

Validate the portable skill package with:

```bash
python -m pytest -q tests/test_skill_package.py
python -m scripts.validate_skill_package --output tmp/vietnam-legal-source-verifier.zip
```

## Repository hygiene

Never commit credentials, local environment files, databases, generated corpus artifacts, or local evaluation output. Preserve the source manifests and their per-source attribution. Keep the skill package self-contained: do not put application code, corpus data, or application dependencies in it. When testing native skill discovery, stage temporary copies outside the repository and remove them after the check.
