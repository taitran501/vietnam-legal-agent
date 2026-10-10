# User flows

## Ordinary legal question

1. The user opens a conversation and types a question in their own words.
2. The assistant uses conversation context to understand the request and
   searches the multi-domain legal corpus.
3. It answers with supporting sources and citations, or says which point could
   not be verified.
4. The user can ask a follow-up in the same conversation.

The welcome screen shows three optional example prompts. They cover different
legal topics and never select or lock the domain for the user's later request.

## Personal situation or procedure

The user describes their circumstances or asks for steps in ordinary chat. The
assistant uses facts already provided, answers supported parts, and asks one
short follow-up only when a missing fact is material. No domain-specific intake
form or case drawer blocks a response.

## Sources and persisted history

The conversation keeps user and assistant messages, source snapshots, and
result metadata. Older case facts remain available as context and are not
deleted when legacy state is normalized.
