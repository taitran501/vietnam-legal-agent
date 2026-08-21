# Guided user flows

## End-to-end flows

| Goal | Entry point | Primary action | Result |
| --- | --- | --- | --- |
| Legal lookup | Composer | Send a question | Answer with citations |
| Case assessment | Welcome or assistant card | Fill the adaptive form, click **Kiểm tra trường hợp** | Preliminary assessment or request for more information |
| Compliance checklist | Welcome or assistant card | Fill the adaptive form, click **Tạo danh sách việc cần làm** | Checklist with actions and supporting citations |

The guided form supports all legal domains (labor, civil/contract, marriage
& family, corporate, land, traffic, EPR, and general) via `detect_legal_domain`
routing. The resolver adapts the field set to the detected domain.

The drawer only opens when the user wants to view or edit the full case
profile. It is not a required step to complete a case.

## Opening the form and resolving fields

```mermaid
sequenceDiagram
    actor User as User
    participant UI as GuidedCaseCard
    participant Draft as useCaseDraft
    participant API as POST /case-form/resolve
    participant Resolver as CaseFormResolver

    User->>UI: Select assessment/checklist goal
    UI->>Draft: create empty draft
    Draft->>API: resolve(task_type, {})
    API->>Resolver: compute base fields
    Resolver-->>API: CaseFormState
    API-->>Draft: fields, counts, errors
    Draft-->>UI: render fields and guidance
    User->>UI: change a field
    Draft->>API: resolve after 250 ms debounce
    API->>Resolver: merge and validate
    Resolver-->>API: dependent fields + new counts
    API-->>Draft: discard if response is stale
```

## Atomic submit and SSE

```mermaid
sequenceDiagram
    actor User as User
    participant UI as GuidedCaseCard
    participant API as POST /chat
    participant Store as Durable history
    participant V4 as V4 runtime
    participant Legal as Retrieval + rule pack

    User->>UI: Click primary button
    UI->>API: message/continue_case + fact_updates
    API->>Store: save user message + assistant placeholder
    API-->>UI: SSE status(turn_id, message ids)
    API->>V4: validate, merge, persist case
    alt Missing or invalid fields
        V4-->>API: input_required + CaseFormState
        API-->>UI: SSE case_update
    else Sufficient data
        V4->>Legal: retrieve active sources and evaluate issues
        Legal-->>V4: evidence assessment
        V4-->>API: structured result + source snapshots
        API->>Store: complete turn and case
        API-->>UI: response_complete
    end
```

## Missing information, retry, and citations

```mermaid
sequenceDiagram
    actor User as User
    participant UI as Result card
    participant API as Backend
    participant Store as History

    UI-->>User: N pieces of information still missing
    User->>UI: fill field inline in the card
    UI->>API: resolve debounce
    API-->>UI: field error or card ready
    User->>UI: Retry if request is retryable
    UI->>API: replay original descriptor
    API->>Store: keep old answer until new one completes
    User->>UI: click citation [n]
    UI-->>User: source drawer focuses on source n
```

## Form state

```mermaid
stateDiagram-v2
    [*] --> idle
    idle --> resolving: open form or change field
    resolving --> editing: resolve succeeded
    resolving --> editing: resolve error, keep draft
    editing --> resolving: debounce change
    editing --> ready: no required fields missing
    ready --> submitting: click primary button
    submitting --> completed: turn finished
    submitting --> needs_information: backend detects new dependency
    submitting --> failed: non-retryable error or broken dependency
    failed --> submitting: Retry
```
