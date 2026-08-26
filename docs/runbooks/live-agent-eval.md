# Live Agent Evaluation Runbook

The `Live Agent Evaluation` workflow is the only path that runs the autonomous
`pipeline-agent` against real OpenAI and Qdrant providers. It is deliberately
`workflow_dispatch`-only and uses the protected GitHub Environment named
`pilot`. Pull-request CI and deterministic replay never substitute for this
evidence.

## What the gate proves

The workflow runs the checked-in 50-case runtime benchmark through
`AgentWorkflowRuntime` and uploads `live-agent-eval.json`. The report includes
the commit, pipeline/config metadata, trace and corpus identifiers, replay
events, source payloads, provider/evaluator status, latency, and per-case
failure codes.

Promotion requires all of the following:

- pass rate at least 70%;
- statutory-anchor accuracy at least 80%;
- context recall at least 75%;
- `provider_status: ok` and `evaluator_status: ok` for every case;
- a terminal event, replay pass, and source payload for every case.

An unavailable provider, evaluator, terminal event, or source payload fails the
workflow even if an aggregate percentage happens to meet the thresholds.

The benchmark is an engineering runtime signal. Its legacy expected anchors do
not become legal ground truth, and this workflow does not require a legal
reviewer or legal approval record.

## Pilot environment setup

An administrator with repository Actions permission must create/configure the
`pilot` environment. Store secret values only in GitHub; never commit them or
print them in workflow logs.

Required environment secrets:

| Name | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Live answer generation and RAGAS judge calls. |
| `QDRANT_CLOUD_URL` | Qdrant Cloud endpoint containing the pilot collection. |
| `QDRANT_API_KEY` | Qdrant Cloud access key. |

Required environment variable:

| Name | Purpose |
| --- | --- |
| `PILOT_LAW_COLLECTION` | Exact Qdrant collection name used by the pilot corpus. |

The job starts an ephemeral Redis 7 service for the runtime cache and uses a
temporary SQLite history database inside the runner. `CORPUS_RUNTIME_MODE=preview`
and `REQUIRE_AUTH=false` are intentional for this isolated evaluation job; they
do not relax production startup requirements or expose a public deployment.

## Run and inspect

From the GitHub Actions UI, choose **Live Agent Evaluation → Run workflow** on
the exact commit to evaluate. With an authenticated GitHub CLI, the equivalent
command is:

```bash
gh workflow run live-agent-eval.yml --ref main
gh run list --workflow live-agent-eval.yml --limit 1
gh run view <run-id> --log-failed
```

Download the `live-agent-eval-<sha>` artifact and retain it with the release
record. The workflow must be rerun after a corpus, model, prompt, or runtime
change; do not reuse an artifact from another commit.

## Current blocker

The repository checkout cannot contain the `pilot` secrets or create the
environment on behalf of an administrator. Until the environment and its
provider/corpus values exist, a manual run must fail at configuration
validation; that is an external setup blocker, not a passing or failing legal
quality result.
