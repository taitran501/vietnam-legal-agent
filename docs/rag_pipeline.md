# Legal chat and retrieval

## Request flow

Every legal topic follows the same chat path:

1. Understand the user question and recent conversation.
2. Preserve named laws, article numbers, dates, and other explicit anchors.
3. Search the content-locked multi-domain corpus.
4. Check source identity, topical relevance, effective-status metadata, and
   whether the retrieved provisions support the requested claim.
5. Generate a concise answer with citations to retrieved sources.
6. Verify citations and supported claims before returning the answer.

A greeting can be answered without legal retrieval. Official-web research is a
separate route and runs only when the user explicitly asks for it. It cannot
silently replace missing corpus evidence.

## Standard source

The corpus manifest and reproducible SQLite build are described in
retrieval/universal-corpus.md. The database contains full-text search fields
for source topic, subject, article heading, source note, and provision text. It
is mounted read-only by the backend.

The optional Qdrant adapter is disabled by default and is not required by the
standard workflow, CI, or live-agent evaluation. No single-domain collection
is a product default.

## Evidence limits

The agent distinguishes source text from its application to user facts. It asks
for clarification only when a missing fact changes the answer. If the source
does not support a requested detail, it says what it could verify and what
remains open. It does not fill gaps with a fixed domain checklist or invented
citations.
