# System overview

## Purpose and scope

The application helps Vietnamese users:

1. look up a legal provision and open the original source document;
2. provide situational information to receive a grounded preliminary assessment;
3. generate a compliance checklist from the same set of facts.

The legal lookup flow and the case flow share history, identity, SSE, and source
snapshots but do not share business decisions. Retrieval finds sources; rule
packs and evidence assessment determine whether there is sufficient basis to
present a result.

## Context diagram

```mermaid
flowchart LR
    U["Business user"] --> B["Browser"]
    B --> F["React application"]
    F --> API["FastAPI API"]
    API --> W["V4 workflow runtime"]
    API --> P["Persistence and session store"]
    W --> R["CaseFormResolver"]
    W --> RP["Versioned domain rule packs (7 legal domains + general)"]
    W --> L["Legal retrieval"]
    L --> Q["Qdrant index"]
    L --> O["Official legal sources"]
    W --> S["Source snapshots"]
    S --> P
    API --> E["SSE stream"]
    E --> F
```

An alternative runtime, `pipeline-agent`, replaces the deterministic V4 graph
with an autonomous ReAct loop (see `autonomous-agent-architecture.md`).
The two runtimes share the same tool registry, domain rule packs, retrieval
layer, and persistence.

## Container and component boundaries

```mermaid
flowchart TB
    subgraph Browser["Browser / React"]
        App["App routing and readiness"]
        Chat["Chat composer and message timeline"]
        Guided["GuidedCaseCard"]
        Fields["CaseFieldList"]
        Draft["useCaseDraft"]
        Editor["CaseFactsPanel full editor"]
        Sources["Source drawer"]
        App --> Chat
        App --> Guided
        Guided --> Draft
        Guided --> Fields
        Editor --> Fields
        Chat --> Sources
    end

    subgraph Backend["FastAPI"]
        Routes["Chat, case-form, sessions routes"]
        Resolver["CaseFormResolver"]
        V4["V4 runtime"]
        History["History and case persistence"]
        Retrieval["Retrieval and source verifier"]
        Routes --> Resolver
        Routes --> V4
        Routes --> History
        V4 --> Resolver
        V4 --> Retrieval
        V4 --> History
    end

    Browser --> Routes
```

## Boundary rules

| Boundary | Owns | Does not own |
| --- | --- | --- |
| UI state | draft, focus, loading, dirty state, presentation copy | legal applicability or field dependencies |
| Case domain | typed facts, field visibility, validation, missing counts | persistence and legal conclusion |
| Legal decision | rule pack, issue coverage, assessment status, next steps | rendering or browser storage |
| Retrieval | candidate documents, active-source filtering, citations | inventing facts or declaring applicability |
| Persistence | ownership, turns, snapshots, replay metadata | changing a submitted fact silently |

## Request lifecycle

`POST /case-form/resolve` is pure and is safe to call while editing. A guided
submit sends one `/chat` request with typed updates. The backend merges and
validates the facts inside the durable turn before retrieval starts. A PATCH is
reserved for the secondary full editor and save-for-later behavior.
