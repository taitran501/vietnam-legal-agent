# Live Agent Evaluation Runbook

The `Live Agent Evaluation` workflow runs the autonomous `pipeline-agent` with the pinned multi-domain legal corpus and a real OpenAI provider. It is `workflow_dispatch`-only and uses the protected GitHub environment named `pilot`. Deterministic pull-request checks do not replace this provider-backed measurement.

## What the gate proves

The workflow runs the checked-in 50-case benchmark through `AgentWorkflowRuntime` and uploads `live-agent-eval.json`. The report records the commit, pipeline/configuration, traces, corpus identifiers, source payloads, provider and evaluator status, latency, and per-case failure codes.

Promotion requires all of the following:

- pass rate of at least 70%;
- statutory-anchor accuracy of at least 80%;
- context recall of at least 75%;
- `provider_status: ok` and `evaluator_status: ok` for every case;
- a terminal event, replay pass, and source payload for every case.

An unavailable provider, evaluator, terminal event, or source payload fails the workflow even if aggregate percentages meet their thresholds. The benchmark is an engineering signal, not legal ground truth.

## Pilot Environment Setup

An administrator with repository Actions permission must create/configure the `pilot` environment. Store secrets only in GitHub.

| Secret | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Live answer generation and evaluator calls. |

The job builds the pinned corpus, starts an ephemeral Redis service, and uses a temporary SQLite history database. `CORPUS_RUNTIME_MODE=preview` and `REQUIRE_AUTH=false` apply only to this isolated workflow.

## Run and Inspect

From the GitHub Actions UI, choose **Live Agent Evaluation → Run workflow** on the exact commit. With GitHub CLI:

```bash
gh workflow run live-agent-eval.yml --ref <branch>
gh run list --workflow live-agent-eval.yml --limit 1
gh run view <run-id> --log-failed
```

Retain the `live-agent-eval-<sha>` artifact with the release record. Rerun the workflow after a corpus, model, prompt, or runtime change; do not reuse evidence from another commit.

## Current Blocker

The protected environment and its secrets are administrator-managed. Until `pilot` has `OPENAI_API_KEY`, a manual run will fail at configuration validation and will not produce a legal-quality result.
