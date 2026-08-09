# Stitch prompt pack

Use the shared base prompt first, then create the five state-specific screens.
Prompt instructions are English; every visible UI label must be Vietnamese.

## Shared prompt

> Design a desktop-first responsive Vietnamese web application named “EPR Compliance Copilot” for manufacturers and importers in Vietnam. It is a legal compliance assistant, not a generic chatbot. Use a calm, trustworthy light legal-SaaS aesthetic with a navy and teal accent palette, strong information hierarchy, generous whitespace, and accessible contrast. The layout has a left conversation-history sidebar, a central chat and evidence workspace, and a right editable case-facts panel. Clearly surface citations, assumptions, missing facts, checklist progress, and safe-stop states. All visible UI copy must be Vietnamese. Do not use a dark dashboard aesthetic, marketing hero imagery, or generic AI visual effects.

## Required states

1. **Welcome / new case**

   > Apply the shared prompt. Show three equally prominent actions: “Tra cứu quy định”, “Đánh giá nghĩa vụ”, and “Lập checklist”. Explain in one sentence that results support legal research and are not legal advice.

2. **Conversation workspace**

   > Apply the shared prompt. Populate a realistic EPR conversation. Show source cards below the answer and a compact, numbered workflow-progress timeline. In the Case Facts panel include role, product or packaging, material, and activity scope.

3. **Missing facts**

   > Apply the shared prompt. The assistant is waiting for business facts, not retrieving more documents. Highlight only the missing fields in amber, show a clear Vietnamese follow-up question, and explain that the system will not infer company data.

4. **Preliminary assessment**

   > Apply the shared prompt. Show a clearly labelled “Đánh giá sơ bộ”, an assumptions area, legal citations, evidence count, and a persistent disclaimer. Do not use a definitive pass/fail compliance badge.

5. **Checklist / safe stop**

   > Apply the shared prompt. Show a compliance checklist with linked evidence and a source drawer. Include an alternative safe-stop state for insufficient evidence: state that the system did not reach a legal conclusion and invite the user to narrow the legal question or provide missing facts.

## Handoff checklist

- Save the Stitch URL and export date.
- Export desktop and mobile screenshots for all five states.
- Map colors, typography, spacing, radii, and state colors into `tokens.json`.
- Record any intentional deviation in a short note beside the screenshots.
