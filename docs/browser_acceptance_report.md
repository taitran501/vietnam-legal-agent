# Browser acceptance report

This report records the user-visible acceptance evidence for the browser
remediation release. The legal corpus remains technically auditable but is not
self-declared legally approved; preview labels are therefore expected.

## Environment

- Date: 2026-08-13
- Browser: Codex in-app Browser, real DOM interactions
- Frontend: Vite at `http://127.0.0.1:4175/`
- Deterministic API: `tests.e2e_backend:app` at `http://127.0.0.1:8010/`
- Corpus hash: `1f9ce661c52bf5aaa2413d980578aea232c8a486d66a7c41ebed72054a92f6d6`
- Implementation commit validated: `e7dfea289323fbdff8ace7d93e0488fabd6d11ca`
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
evaluation passed `60/60`. The full Python gate passed `383 passed, 3 skipped`.
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
