# Pipeline V4 behavior contract

Pipeline V4 is a server-selected workflow for ordinary Vietnamese legal chat.
The browser can request a response style such as assessing a situation or
building a checklist, but those choices do not activate a domain-specific rule
engine or a required-facts form. All legal requests use the same retrieval,
evidence assessment, generation, and citation verification path.

## Runtime and corpus

The content-locked Ministry of Justice corpus is the only default source for
legal chat. Qdrant retrieval is disabled by default and cannot silently
replace the multi-domain corpus. If the corpus database is missing or invalid,
the service reports it unavailable.

Preview mode supports technical and user-flow validation; it does not grant
legal approval. Production currently rejects the generated universal corpus
until it is bundled and passes the release and independent legal-review gates.

## Request contract

`POST /api/v1/chat` accepts the existing `query`, `conversation_id`,
`session_id`, and `mode` fields. Optional `operation`, `intent_hint`,
`interaction_source`, and case fact fields remain for client compatibility.
New turns do not require `/api/v1/case-form/resolve`, a case drawer, or a
domain-specific list of missing facts. Legacy case state is normalized to the
general case type when read or updated; user facts remain available as
conversation context.

The normal workflow is:

```text
validate -> load conversation -> understand intent -> retrieve legal sources
-> assess evidence -> generate answer -> verify citations -> persist
```

Situation assessment and checklist requests are expressed as ordinary legal
queries. They may receive a concise clarification when a material ambiguity
prevents a useful answer, but the agent should answer the parts supported by
the current sources and facts without waiting for a full form.

## Domain interpretation

Domain labels are retrieval hints, not separate assessment engines. The query
and conversation context select relevant sources; a single keyword must not
force a domain classification. Every legal topic uses the same multi-domain
retrieval, evidence assessment, generation, and citation verification path.

## Evidence and answer delivery

- State statutory citations, deadlines, penalties, and legal effects only when
  retrieved sources support them.
- Do not use fixed issue coverage requirements, domain-specific rule-pack
  conclusions, or prewritten checklists as substitutes for retrieved sources.
- Treat a user's facts as unverified unless a source independently confirms
  them.
- Ask for one clarification only when a missing fact blocks the central part
  of the answer. Otherwise state the assumption and answer what the sources
  support.
- If sources do not support an answer, explain what is missing and offer the
  configured official-source research action when available.

## Local checks

```powershell
python -m pytest -q tests/agent tests/tools
Set-Location frontend-react
npm run test
npm run build
```

Live retrieval, the universal-corpus audit, Docker smoke tests, and full browser
trajectories are separate acceptance evidence. Do not claim those gates pass
until the real services and corpus artifact have completed them.
