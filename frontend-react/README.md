# Vietnam Legal Agent UI

React is the Vietnamese chat interface for asking legal questions, describing
situations, and requesting procedural steps in natural language. It displays
agent progress, evidence, citations, assessments, checklists, and safe-stop
states.

## Main capabilities

- Conversation history sidebar and route-based conversation URLs.
- SSE chat with the compatible `status`, `response_chunk`,
  `response_complete`, and `workflow_step` events.
- Three optional legal-intent shortcuts; the user can also ask freely in chat.
- Evidence/result cards for missing facts, preliminary assessments, checklists,
  citations, and no-evidence safe stops.
- Typed API clients, Zustand state, Vitest component tests, and Playwright
  workflow tests.

## Development

```bash
npm install
cp .env.example .env
npm run dev
```

`VITE_API_BASE_URL` defaults to `http://localhost:8000`. In an authenticated
deployment configure `VITE_OIDC_ISSUER`, `VITE_OIDC_CLIENT_ID`, and the exact
registered `VITE_OIDC_REDIRECT_URI`; the browser uses authorization-code PKCE
and never receives a backend API key.

## Static deployment

The Vite frontend can be deployed independently from the FastAPI container.
For a static host, use `frontend-react` as the project root, `npm ci` as the
install command, `npm run build` as the build command, and `dist` as the output
directory. Set `VITE_API_BASE_URL` to the HTTPS backend origin and add the exact
frontend origin to the backend's `ALLOWED_ORIGINS`. The API client, SSE stream,
document upload, and DOCX export all use the same API base setting. If the host
proxies `/api/*` to the backend under the frontend origin, leave
`VITE_API_BASE_URL` empty instead.

## Validation

```bash
npm run test
npm run build
npm run test:e2e
```

The visible product copy is Vietnamese. The design brief and tokens live in
`../docs/design/`; a Stitch export is not considered approved until its URL and
screenshots are added there after design review.
