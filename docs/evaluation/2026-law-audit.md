# 2026-law evaluation audit

Status: **pending legal-source audit**.

The checked-in fixture at `data/eval/audited/2026-law-follow-up.json` records the
two-turn interaction contract without asserting that any instrument number,
date, title, or effective-status claim is correct. It is intentionally
informational until a reviewer matches every claim to the authoritative corpus.

The audit must record:

- instrument number, issuing authority, title, document type, promulgation date,
  and effective date;
- canonical source ID, precise article/clause anchor, official URL, corpus SHA,
  and audit date;
- supported claims, unsupported claims, and claims intentionally omitted;
- the expected follow-up result: additional verified items, a grounded
  no-more-items result, or a clarification request.

No generated answer is accepted as legal ground truth. After the audit is
complete, change `audit.status` to `audited`, fill the reviewer/corpus fields,
and add the source and claim records required by the evaluation contract.
