---
name: vietnam-legal-source-verifier
description: Verify Vietnamese legal answers against official source text, amendments, effective dates, and precise provisions; separate user facts from verified law and stop when evidence is insufficient.
---

# Vietnam legal source verifier

Use this skill when a user asks for Vietnamese law, a legal procedure, or a preliminary analysis that depends on the current or historical effect of a legal instrument.

This workflow supports legal research. It does not provide a formal legal opinion, guarantee an outcome, or replace a qualified professional's review.

## Verification workflow

1. **Define the question and time.** Identify jurisdiction, topic, requested result, and the relevant date or period. For a case, separate each user-supplied fact from each fact established by a source. Ask one focused question when a missing fact could change the applicable rule.
2. **Find and inspect a primary source.** Search official government or competent-agency publication systems. Candidate portals include `vanban.chinhphu.vn`, `vbpl.vn`, and `phapdien.moj.gov.vn`; confirm that the page is the relevant official record. If the official record displays the complete instrument text, inspect the requested provision there. If it contains metadata only, follow its link to the official original text. For a scanned PDF, use an available Vietnamese OCR or page-rendering tool. Compare OCR with the rendered page when visual inspection is available; otherwise cross-check with an independent OCR engine or a second OCR pass using a different layout mode. Rely only on clear, concordant text, and stop if the wording is uncertain or the checks disagree. A search snippet, dataset, model memory, private article, or repost is a discovery aid, not source verification.
3. **Check identity and legal effect.** Match the instrument number, title, issuer, publication date, and relevant provision. For a current-law question, inspect later amendments, replacement or repeal provisions, effective dates, and transition clauses through the requested as-of date. Distinguish a consolidated text from the amending instrument when the relationship matters. If you cannot verify status, say so.
4. **Resolve disagreement.** Compare the actual official texts and dates, not only summaries. Explain which source is more authoritative or later and why. If official materials conflict or the relevant scope cannot be resolved, report the conflict and do not state a definitive rule.
5. **Apply only what the source supports.** Explain the provision in plain language and connect it to the user facts without treating allegations or assumptions as verified. Identify missing facts and limits. Do not infer a guaranteed legal outcome from a general rule.
6. **Cite precisely.** Name the instrument, number, issuer, article/clause/point, relevant date or status, and direct official URL. Make clear whether text is quoted or paraphrased. Do not cite a provision you did not inspect or claim a source supports more than it says.
7. **Stop safely when needed.** If no suitable primary source is available, the source is incomplete, scanned text cannot be verified visually or cross-checked through a second OCR pass, or the key facts are missing, state what could and could not be verified, avoid a firm conclusion, and identify the exact source or fact needed to continue.

## Answer shape

Use a short answer first, followed by:

- **Căn cứ đã kiểm tra:** instrument and precise provision, official URL, and effective/as-of status;
- **Áp dụng:** which user facts are assumed and how the verified text relates to them;
- **Chưa xác minh / cần làm rõ:** material source gaps, conflicting texts, or missing facts;
- **Giới hạn:** preliminary research only when the user asks for an individual legal conclusion or high-impact decision.

Keep the answer proportionate to the evidence. If verification fails, lead with that limitation rather than presenting a speculative result as likely law.

## Reference material

- [Official source discovery](references/official-sources.md)
- [Citation and evidence policy](references/citation-policy.md)
- [Legal limitations and safe stops](references/legal-limitations.md)
- [Evaluation cases](tests/evaluation-cases.json)

## Review rubric

A response fails critically if it invents a source or provision, attributes a rule to a source that does not contain it, misstates a verified effective date, treats user assertions as independently verified, or gives a certain conclusion after acknowledging that decisive evidence is missing. See each evaluation case for its expected behaviors and critical failures.
