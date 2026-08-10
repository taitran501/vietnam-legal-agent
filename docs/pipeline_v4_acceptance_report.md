# Pipeline V4 local acceptance report

Status: **V4 default cutover**. The server and local Compose stack now use
`AGENT_PIPELINE_VERSION=pipeline-v4` by default. V3 remains available only as
an explicit rollback setting while the remaining live quality gates are
measured.

## Verified locally

- Behavior contracts: a quick action only pre-fills the composer; the
  screenshot regression enters `case_assessment`, reports
  `needs_information`, makes no retrieval call, and renders no assessment
  result card.
- V4 issues are retrieved and covered independently.  A completed assessment
  requires every mandatory issue; missing Appendix XXII evidence stops safely.
- V4 SSE emits `workflow_step`, `input_required`, `case_update` and a
  backwards-compatible `response_complete` event.
- The Docker V4 indexer extracted and audited Appendix XXII from the source
  `.doc`, accepted 196 provenance-bearing canonical records, and built the
  versioned collection
  `law_epr_ac955ae960a7_legal_structure_v2_v4_appendix1_openai_text_embedding_3_small_v1`
  with 1,324 points.  Its second run reused that collection without an
  embedding request.
- An isolated V4 backend returned `/api/v1/ready = 200` against that alias.

## Still required before calling the cutover fully accepted

- Measure the full route, retrieval and live E2E quality gates specified for
  V4 (macro F1, Hit@1, coverage, P@1/NDCG/Recall and p95 latency).
- Run the complete frontend suite and the real-stack Playwright flows against
  the rebuilt V4 backend.
- Record the final commit SHA, Appendix artifact hash and measured metrics,
  then switch the default and retire V3 in a separate reviewed cutover.

This report deliberately does not mark unmeasured live metrics as passed.
