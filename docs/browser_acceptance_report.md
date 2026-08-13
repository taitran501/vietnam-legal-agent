# Browser acceptance report

This report records the user-visible acceptance evidence for the browser
remediation release. The legal corpus remains technically auditable but is not
self-declared legally approved; preview labels are therefore expected.

## Environment

- Date: 2026-08-13
- Browser: Codex in-app Browser, real DOM interactions
- Frontend: Vite at `http://127.0.0.1:4175/`
- Deterministic API: `tests.e2e_backend:app` at `http://127.0.0.1:8010/`
- Corpus hash: `1e8635ee2f739a96d5bc079f3f607cacc0a485472048dd7af47cf15c02a6b897`
- Implementation commit validated: `0fad1222ad86edfcc8f7200e4547dd2edf75b59a`
- Runtime mode: `preview`

## Direct browser journey

The in-app Browser completed the following actions against the running app:

1. Opened the welcome screen and verified the preview warning while history was
   still available.
2. Selected the suggested Article 77 question and sent it.
3. Verified the durable timeline, assistant answer, citation markers, source
   list, and preview corpus warning.
4. Clicked citation `[1]` and verified that the source drawer focused source 1
   with title, instrument number, anchor, excerpt, and corpus status.
5. Started a checklist, opened the case drawer, changed the required facts,
   verified the primary save button became enabled, and clicked **Lưu và tiếp
   tục lập checklist**.
6. Verified the drawer closed, the update toast appeared, and the next
   workflow question was rendered.

## Automated evidence

The complete browser suite passed on the implementation commit above:

```text
19 passed
  desktop, tablet, and mobile layouts
  direct URL, root reset, browser back, and session retry
  stop/reload durability, feedback reload, and regeneration rollback
  case task-type save and checklist continuation
  production corpus block and owned history
  accepted official-web source and unknown explicit article safe-stop
```

Vitest passed `23/23`, the production build passed, and deterministic route
evaluation passed `60/60`. The full Python gate passed `384 passed, 3 skipped`.
The browser suite used the deterministic local backend; live service gates
remain listed below.

## Required external gates

The following are not inferred from deterministic browser success and must be
recorded separately before production promotion:

- external legal approval and approved corpus-as-of date;
- live Qdrant immutable collection audit and alias promotion;
- live official-web provider smoke;
- Compose readiness with the deployment's real PostgreSQL/Redis/Qdrant/OIDC
  services;
- two-user OIDC isolation journey;
- accepted p95 latency comparison against the production baseline.
