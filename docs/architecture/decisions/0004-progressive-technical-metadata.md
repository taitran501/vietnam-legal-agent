# ADR 0004: Technical Metadata Uses Progressive Disclosure

- **Status:** accepted
- **Context:** Users frequently encountered internal codes such as `corpus`, `workflow`, `trace`, and other system identifiers in answers, the source drawer, and the timeline.
- **Decision:** Default copy uses business language ("Legal Document Repository", "Legal Basis", "Enterprise Information", "Unable to Conclude"). Source IDs, amendment metadata, trace IDs, and version numbers are placed in a reference/support section; traces are only displayed when a debug flag is enabled.
- **Consequences:** Developers still have access to debug data when needed, but non-technical users no longer need to understand the internal architecture to complete their tasks.
