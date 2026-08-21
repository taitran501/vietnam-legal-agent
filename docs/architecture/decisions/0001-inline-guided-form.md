# ADR 0001: Inline Guided Form instead of Drawer-First

- **Status:** accepted
- **Context:** Non-technical users had to open the drawer repeatedly to fill in individual fields, even though the backend already knew the list of missing information.
- **Decision:** An adaptive form displays inline in the welcome screen or the latest assistant message. An active card accepts input and has a single primary submit button.
- **Consequences:** Fewer clicks and preserved context; history cards are read-only, and the UI must handle dynamic fields. The drawer still exists for full editor / save-for-later flows.
- **Rejected:** Forcing users to open the drawer after every follow-up question.
