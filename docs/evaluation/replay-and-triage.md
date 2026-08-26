# Replay and quality triage

The evaluation loop is intentionally split into three stages:

1. `scripts.replay_agent_eval` replays an engineering fixture through the runtime and writes
   SSE, trace, retrieval, source-drawer and structured verification evidence.
2. Quality feedback is stored as a redacted, trace-linked triage item. An
   engineering quality owner marks it reproduced/accepted/rejected/deferred
   through the quality-admin API.
3. `scripts.export_quality_feedback` exports accepted items as replay fixtures.
   The export is for regression/debugging and never acts as legal ground truth
   or a human-approval gate.

The replay report is the join key for debugging: it records the commit SHA,
pipeline/model/config metadata, conversation and trace IDs, every SSE event,
tool trajectory, retrieved documents, source-drawer payload, and structured
failure taxonomy. A provider or evaluator outage is recorded as unavailable;
it is never converted into a passing score.

## Deterministic replay

```powershell
python -m scripts.replay_agent_eval `
  --fixture data/eval/examples/legal-follow-up.json `
  --mode deterministic `
  --output artifacts/evaluation-replay.json
```

Deterministic replay uses an in-memory history and runner adapter. It validates
event ordering, multi-turn identity, report structure and verifier plumbing;
it is not legal ground truth and does not require manual case approval.

## Live replay

Live replay is explicit and may call the configured provider/corpus:

```powershell
python -m scripts.replay_agent_eval `
  --fixture data/eval/examples/<fixture>.json `
  --mode live `
  --output artifacts/evaluation-replay-live.json
```

The Promptfoo workflow runs deterministic cases in PR CI. It is only a matrix
and CI wrapper around the checked-in replay runner. Its Python assertion checks
the internal verifier's structured outcome, claim support and citation mapping,
source-drawer payload (including canonical source URL and uniqueness), and the
stable failure taxonomy. A replay/provider adapter exception is serialised as
a failing artifact instead of becoming a passing or missing case. Provider or
evaluator-unavailable statuses fail the engineering gate, while legal-domain
ground truth remains outside this project's framework/tracing acceptance scope.

