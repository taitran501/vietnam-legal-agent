# Stitch UI Selection

## Review Scope

The exported Stitch design set was used to review 18 HTML screens and reference boards. The binary export is intentionally kept outside this repository; this file records only the design decisions that were carried into the React application.

The product shell is intentionally generic ("Vietnam Legal Agent"), while the interface states that the currently indexed corpora cover multiple legal domains. This avoids presenting the product as a general Vietnamese-law system before all targeted domains are available.

## Adopted Screens and Patterns

| Stitch Screen or Board | Adopted Behavior |
| --- | --- |
| Desktop welcome, expanded sidebar | Main navigation, conversation history, centered composer, and restrained welcome hierarchy |
| Desktop welcome, collapsed sidebar | A real 64 px icon rail rather than removing navigation completely |
| Completed answer | A focused 820 px reading stream, subtle user message, source trigger, and persistent composer |
| Clarification / waiting for information | An inline safe pause with an optional contextual data drawer |
| Source reference drawer | A temporary 420 px right drawer with document title, legal anchor, relevance, and quoted evidence |
| Mobile welcome and mobile conversation | Top app bar, history drawer, full-width reading flow, safe-area-aware composer, and no permanent side panel |
| Error and notification board | Inline insufficient-evidence, technical-error, offline, and rate-limit patterns |
| History management board | Search, rename, delete confirmation, loading skeleton, and empty history states |
| Design handoff board and `DESIGN.md` | Be Vietnam Pro, Noto Serif for the welcome heading only, teal accent, warm white canvas, 264/64 px sidebar, and reduced-motion behavior |

## Adapted Rather Than Copied

- The permanent EPR case panel was replaced by a contextual drawer. It appears only for assessment or checklist flows that have an active case.
- The source drawer does not open while retrieval is running. It opens only after evidence exists and the user selects the source action.
- Unsupported attachment, voice, model selection, sharing, saved-document, and settings controls were not added.
- Domain-specific examples remain in the welcome suggestions because they match the current corpora, but the navigation and component model are domain-neutral.
- Tablet uses the 64 px rail and opens history as a drawer. This fixes the clipped tablet export.
- Workflow progress is compact by default and can be expanded to inspect the bounded action sequence.

## Excluded Screens

- The three-column retrieval screen was excluded because it exposes sources too early and leaves too little room for the answer.
- The exported tablet welcome screen was excluded because its content is visibly clipped on the left.
- Duplicate completed-answer and clarification variants were consolidated into one responsive implementation.
- The component handoff board and state board remain specifications; they are not runtime routes.

## Runtime State Mapping

| Agent/UI State | React Presentation |
| --- | --- |
| Empty / ready | Welcome screen with scoped suggestions |
| Understanding / retrieving / verifying | Compact expandable workflow status |
| Awaiting user input | Inline clarification card; optional case-data drawer |
| Streaming | Assistant row with streaming cursor and stop action |
| Completed | Evidence-grounded answer and source drawer trigger |
| Insufficient evidence / safe stop | Amber safe-stop card without a legal conclusion |
| Technical error | Inline error card with retry action |
| Offline | Single connection banner; composer disabled |
| Mobile/tablet navigation | Overlay history drawer or tablet icon rail |

## Validation Targets

- Desktop: 1280 px and 1600 px widths.
- Tablet: 900 × 1024 with the icon rail.
- Mobile: 390 × 844 with no horizontal overflow.
- Source and case drawers: at least 390 px wide on desktop and full-width up to 420 px on small screens.
- Motion: 180–220 ms for overlays and drawers, disabled under `prefers-reduced-motion`.
