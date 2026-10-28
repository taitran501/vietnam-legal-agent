---
name: legal-evidence-engineering
description: Review and change Vietnam Legal Agent code while preserving source-grounded legal behavior, explicit safety contracts, and reproducible engineering evidence.
---

# Legal evidence engineering

Use this skill when changing retrieval, source metadata, legal-answer generation, citations, safety checks, or evaluation in this repository.

## Review principles

1. **Trace claims to evidence.** Follow the retrieved source text and metadata through retrieval, verification, answer construction, persistence, and display. Keep user-provided facts visibly separate from verified legal facts.
2. **Verify current law.** For questions about current legal effect, check official source text, amendments, effective dates, and transition provisions. Record what source and snapshot were checked. Do not treat an indexed corpus as current merely because it is content-locked.
3. **Handle uncertainty explicitly.** When a source is missing, stale, inaccessible, or inconsistent, show the gap and ask for the information needed to continue. Do not fill it with model memory or an unverified citation.
4. **Use explicit rules when justified.** Rules for schema validation, authorization, bounded resource use, citation parsing, fail-closed checks, or a legally grounded narrow requirement are acceptable. A legal rule must identify its authority, scope, effective period, rationale, and regression cases. Avoid wide keyword maps and ad hoc query-specific branches without measured evidence.
5. **Keep evaluation honest.** Synthetic fixtures test engineering contracts; they are not legal ground truth. Report deterministic/local, provider-backed, and production evidence separately.
6. **Preserve contracts.** Check API schemas, durable state, source-manifest formats, and workflow behavior before changing them. Keep unrelated module restructuring out of a focused fix unless required.

## Change checklist

- [ ] Identify the source contract and affected user flow.
- [ ] Confirm that legal claims can be traced to retrieved source text and effective-date metadata.
- [ ] Keep user facts, source facts, and model inferences distinct.
- [ ] Add or update a focused regression test for the contract changed.
- [ ] Verify that missing or conflicting evidence produces a safe, explicit result.
- [ ] Run the smallest relevant checks, then the repository checks required by the change.
- [ ] State exactly what was verified and what remains outside the evidence.

For portable source verification outside this application, use `skills/vietnam-legal-source-verifier/SKILL.md`.
