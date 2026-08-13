# Browser acceptance report — Guided User Experience Refactor

**Validation date:** 2026-08-14  
**Application validation commit:** `9bb8ab7` (`refactor: make case workflows inline and guided`)  
**Scope:** Vietnamese EPR lookup, guided assessment, guided compliance checklist entry, source inspection, error/retry behavior, and responsive layouts.

This is a new release report. The previous acceptance reports remain historical
and are not rewritten to describe this refactor as if they had passed it.

## Validated user paths

- Welcome → **Kiểm tra trường hợp của doanh nghiệp** → adaptive fields → one chat submit → preliminary result.
- Packaging branch reveals revenue and reuse fields; reuse `Có` reveals the recovery-rate field.
- Invalid numeric input is rejected in the field and does not create a chat turn.
- Resolve failure keeps the in-memory draft; submit failure shows one actionable error card and keeps the form for another attempt.
- Checklist entry uses the same inline field renderer and a single primary action.
- Legal lookup remains composer-first and citation markers open the relevant source drawer.
- Unknown explicit article (`Điều 999`) safe-stops without presenting unrelated candidate sources.
- Stop, reload, feedback restore, regeneration failure/retry, route navigation, history retry, and official-web source labeling remain covered.
- Mobile, tablet, and desktop layouts were exercised without requiring the drawer for the primary case path.

## Automated results

| Gate | Result |
| --- | --- |
| Python `pytest` | **390 passed, 3 skipped** |
| Ruff | **pass** |
| Vitest | **11 files, 29 tests passed** |
| TypeScript/Vite production build | **pass**; existing bundle-size warning remains |
| ESLint | **pass with 1 existing warning** in `src/utils/markdown.tsx` |
| Mocked + real FastAPI Playwright | **20 passed** |
| In-app browser smoke | **pass** on the guided assessment path |
| Mypy | **not clean**: 46 existing errors remain in legacy backend/dependency typing; no errors remain in the new resolver/session changes |

The Playwright run used the deterministic FastAPI service and covered both the
mocked frontend contract and the real local SSE service. The in-app smoke was
performed against the local preview service and confirmed the rendered form,
dependent fields, single submit, result hierarchy, and user-facing fact labels.

## Release boundaries

This report does not claim legal approval, production corpus promotion, live
OIDC provider validation, live Qdrant/Compose readiness, or an accepted
production p95 baseline. Preview mode is intentionally visible in the UI, and
production remains blocked until those external gates are completed.

For the architectural contract and test ownership, see
[the architecture index](README.md), [guided flows](architecture/guided-user-flows.md),
and [the testing strategy](architecture/testing-strategy.md).
