# Pipeline V4 local acceptance report

Status: **V4 test matrix accepted locally**. The server-selected runtime is
`pipeline-v4`; V3-only manifests and trajectory tests were retired after the
V4 report passed. The previous V3 collection and Git tag remain rollback
artifacts.

## Evaluated build

- Evaluated commit: `4835d8e` (`test: complete V4 behavior and integration matrix`)
- Corpus ID: `epr`
- Corpus SHA256: `ac955ae960a7b4d3499c8633c30593bfe55795bcb5a5665fa86e510a9ece1695`
- Appendix XXII artifact SHA256: `08be57c08ce4a266192bb1f1f2570cb92409f70f65f835bc8ce61f6fe6dc4e39`
- Rule-pack version: `epr-article-77-v1`
- Embedding profile: `openai-text-embedding-3-small-v1`
- Embedding model/dimensions: `text-embedding-3-small` / `1536`
- Index schema: `legal-structure-v2-v4-appendix1`
- Active collection alias: `law_collection`
- Indexed points: `1,324`

## Quality gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Python unit/API/contract suite | PASS | 345 passed, 3 skipped |
| V4 route matrix | PASS | 60/60; deterministic route macro-F1 = 1.0 |
| V4 retrieval matrix | PASS | 60/60; P@1 = 1.0, NDCG@3 = 1.0, Recall@5 = 1.0, explicit Hit@1 = 100% |
| V4 deterministic trajectories | PASS | 40/40; issue coverage = 1.0, citation rate = 1.0, p95 = 93.84 ms |
| V4 live trajectories | PASS | 40/40 on source-mounted real stack; issue coverage = 1.0, citation rate = 1.0, p95 = 1,522.73 ms |
| Quick-action prefill | PASS | 0 network requests before explicit submit |
| FAQ runtime use | PASS | 0 FAQ action/source occurrences in V4 tests and trajectories |
| Missing facts | PASS | All decision-fact gaps return `needs_information` |
| Assessment/checklist completion | PASS | Completed results cover all required issues and material claims have citations |
| Web research boundary | PASS | Web route is explicit; no automatic fallback in the tested V4 paths |
| SSE contract | PASS | Stable trace ID, contiguous sequence, V4 pipeline envelope, progressive rendering and cancellation |
| Frontend unit/build | PASS | Vitest 14/14; production build succeeds |
| Browser E2E | PASS | Playwright 11/11, including mocked and real FastAPI/multi-turn flows |
| Real-service integration | PASS | 2/2 with PostgreSQL, Redis, Qdrant and V4 SSE/trace API |
| Index idempotence | PASS | Second indexer run exited 0, reused the same versioned collection without embedding calls |
| Readiness | PASS | Final Compose stack returned HTTP 200; database, Redis, Qdrant, OpenAI, alias, corpus, Appendix and embedding metadata ready |
| Final Docker smoke | PASS | Main image: 2/2 live SSE trajectories; p95 = 1,166.08 ms; out-of-scope and insufficient-evidence safe-stops verified |

## Runtime artifacts

The deterministic report is generated with:

```powershell
python -m tests.eval.run_eval --suite all --output data/eval/v4-deterministic.json
```

The live 40-case report is generated with:

```powershell
python -m tests.eval.run_eval --live --live-url http://127.0.0.1 --suite e2e --output data/eval/v4-live.json
```

Both reports are ignored runtime artifacts. The versioned manifest, test
contracts, and this concise report are the reviewable acceptance evidence.

## Notes

The standard Compose image was rebuilt locally after the evaluated code
checkpoint. The final `/api/v1/ready` check and main-image SSE smoke passed
after that restart. No CI/CD workflow was added. Live tests use the configured
OpenAI embedding/generation services and therefore remain an explicit local
command, not part of the default unit suite.
