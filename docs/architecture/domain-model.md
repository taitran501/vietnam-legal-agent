# Domain model

## Core contracts

```mermaid
classDiagram
    class CaseFormState {
        +string form_version
        +TaskType task_type
        +FormStatus status
        +map~string,FactValue~ facts
        +list~CaseField~ fields
        +list~string~ missing_facts
        +map~string,string~ validation_errors
        +int completed_count
        +int required_count
    }
    class CaseField {
        +string key
        +string label
        +string group
        +int display_order
        +FieldKind kind
        +bool required
        +Importance importance
        +bool missing
        +string value
        +string help_text
        +list options
    }
    class FactValue {
        +string value
        +FactSource source
        +ConfirmationStatus confirmation_status
        +bool verified
    }
    class CaseStateV4 {
        +string schema_version
        +TaskType task_type
        +CaseStatus status
        +map facts
        +list missing_facts
        +list fields
    }
    class AssessmentResult {
        +AssessmentStatus status
        +string conclusion
        +list reasons
        +list assumptions
        +list next_steps
    }
    class SourceSnapshot {
        +string source_id
        +string title
        +string anchor
        +string official_url
        +string excerpt
        +string effective_status
    }
    class Turn {
        +string turn_id
        +MessageStatus status
        +string replay_descriptor
        +int user_message_id
        +int assistant_message_id
    }

    CaseFormState o-- CaseField
    CaseFormState o-- FactValue
    CaseStateV4 o-- FactValue
    CaseStateV4 --> AssessmentResult
    AssessmentResult o-- SourceSnapshot
    Turn --> CaseStateV4
```

The diagram describes data ownership, not React functions as object-oriented
classes. `CaseFormState` is the resolver response; `CaseStateV4` is the
persisted case contract; presentation fields are hydrated without a migration.

## Component responsibility

```mermaid
flowchart LR
    Card["GuidedCaseCard\nactive inline form"] --> Draft["useCaseDraft\ndraft + debounce + stale guard"]
    Draft --> Resolver["case-form API\nserver-owned dependency"]
    Card --> Fields["CaseFieldList\npure renderer"]
    Editor["CaseFactsPanel\nsecondary full editor"] --> Fields
    Card --> Result["WorkflowResultCard\noutcome + next steps"]
    Result --> Sources["Source drawer\nsource snapshot"]
```

`GuidedCaseCard` owns the primary journey. `CaseFactsPanel` owns save-for-later
editing only. `CaseFieldList` never performs API calls. `useCaseDraft` does not
write sensitive draft data to local or session storage. `CaseFormResolver` does
not persist data and never creates a legal conclusion.
