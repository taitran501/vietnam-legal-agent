# Bounded workflow contract

The active runtime is one LangGraph workflow with a closed action surface:

```text
validate -> load_context -> understand -> route -> validate_inputs
  -> retrieve -> evidence_gate -> compose -> verify -> persist
```

There is no free-form planner and no autonomous tool discovery. The transition
policy limits each run to two legal retrieval attempts and one answer repair.

`QueryPlan` is the validated result of understanding. It contains route,
confidence, follow-up status, standalone query, explicit anchors, legal topics,
explicit facts, missing facts, and explicit web-research intent. Model output
cannot introduce a route or fact outside the schema. A low-confidence route
causes a clarification question rather than retrieval.

The active case is conversation-scoped data, not a user-profile memory. It
contains only facts explicitly supplied for the current assessment or checklist
and is resumed only within that conversation. Recent messages and a compact
summary form the short-term context used for follow-up rewriting.

Trace events contain operational metadata only: decision reason, route,
candidate IDs/anchors/scores, evidence decision, verifier decision, tool
latency, and termination reason. Recursive allowlisting prevents raw query,
history, prompts, evidence text, answers, and credentials from entering the
trace store.
