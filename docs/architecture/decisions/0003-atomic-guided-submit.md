# ADR 0003: Guided Submit Uses an Atomic Chat Turn

- **Status:** accepted
- **Context:** The old flow issued a PATCH to update the profile and then sent `continue_case` separately, adding an extra request, risking synchronization issues, and creating the impression that users had to save multiple times.
- **Decision:** The guided form sends typed `fact_updates` directly to `/chat`. The backend validates, merges, persists the case, and evaluates it all within a single durable turn. PATCH is reserved only for the full editor / save-for-later flow and backward compatibility.
- **Consequences:** Replay descriptors must preserve facts and intent; the transaction boundary is clearer; the form must be locked during submission.
