# Replay and quality triage

The evaluation loop is intentionally split into three stages:

1. `scripts.replay_agent_eval` replays a fixture through the runtime and writes
   SSE, trace, retrieval, source-drawer and structured verification evidence.
2. Quality feedback is stored as a redacted, trace-linked triage item. A
   reviewer marks it reproduced/accepted/rejected/deferred through the
   quality-admin API.
3. `scripts.export_quality_feedback` exports accepted items as **pending**
   audited fixtures. The source ledger must be completed before a fixture can
   block promotion.

The replay report is the join key for debugging: it records the commit SHA,
pipeline/model/config metadata, conversation and trace IDs, every SSE event,
tool trajectory, retrieved documents, source-drawer payload, and structured
failure taxonomy. A provider or evaluator outage is recorded as unavailable;
it is never converted into a passing score.

## Deterministic replay

```powershell
python -m scripts.replay_agent_eval `
  --fixture data/eval/audited/2026-law-follow-up.json `
  --mode deterministic `
  --output artifacts/evaluation-replay.json
```

Deterministic replay uses an in-memory history and runner adapter. It validates
event ordering, multi-turn identity, report structure and verifier plumbing;
it is not legal ground truth.

## Live replay

Live replay is explicit and may call the configured provider/corpus:

```powershell
python -m scripts.replay_agent_eval `
  --fixture data/eval/audited/<audited-case>.json `
  --mode live `
  --output artifacts/evaluation-replay-live.json
```

The Promptfoo workflow runs deterministic cases in PR CI. It delegates quality
semantics to the internal verifier and treats pending legal audits as
informational rather than passing them as audited quality evidence.

