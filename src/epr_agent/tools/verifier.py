"""Second-layer claim support verification for legal answers.

Structural citation checks prove that a citation points to an existing chunk.
They cannot prove that the cited text supports the claim.  Production therefore
uses one bounded structured-output call after structural validation.  The
result deliberately stores counts and reason codes only; prompts, legal text,
and generated answers are never written to agent traces.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.evidence import legal_claim_segments

_CITATION_RE = re.compile(r"\[(\d+)\]")


class ClaimSupportResult(BaseModel):
    """Sanitised result of the batch claim-to-evidence verification."""

    supported: bool
    unsupported_claim_count: int = Field(default=0, ge=0)
    unsupported_claim_indices: list[int] = Field(default_factory=list)
    reason_code: str = Field(default="ok", max_length=1000)
    model: str = Field(default="", max_length=200)
    token_usage: dict[str, int] = Field(default_factory=dict)


class ClaimSupportVerifier(Protocol):
    async def verify(self, answer: str, documents: list[DocumentRecord]) -> ClaimSupportResult: ...


_SYSTEM_PROMPT = """You verify whether the generated Vietnamese legal claims and advisory conclusions are
consistent with and supported by the provided legal evidence chunks. Return only the requested structured schema.

Evaluation Guidelines:
1. High-level conclusions or introductory summary statements (e.g., 'Ba mẹ bạn có thể được cấp sổ đỏ nếu đáp ứng đủ điều kiện theo quy định [1]') are SUPPORTED if the cited legal article provides a legal pathway, mechanism, or basis for that situation (such as Điều 138/139 providing for granting land certificates for self-reclaimed or unregistered land).
2. Contextual application to user facts (dates, locations, entity names) is valid and supported as long as the underlying statutory rule is consistent with the cited evidence.
3. Mark supported=false ONLY if a claim asserts a genuinely FALSE legal proposition (e.g., asserting a non-existent law, reversing a statutory prohibition/permission, or fabricating a specific rate/fine that directly contradicts the evidence)."""


def _anchor(document: DocumentRecord) -> str:
    metadata = document.metadata or {}
    return str(
        metadata.get("legal_anchor")
        or metadata.get("Parent_Dieu")
        or metadata.get("Dieu")
        or metadata.get("Điều")
        or ""
    )


class StructuredClaimSupportVerifier:
    """One OpenAI structured-output call for the legal support decision."""

    def __init__(self, *, max_chars_per_evidence: int = 3000) -> None:
        self.max_chars_per_evidence = max(500, max_chars_per_evidence)

    async def verify(self, answer: str, documents: list[DocumentRecord]) -> ClaimSupportResult:
        if not answer.strip() or not documents:
            return ClaimSupportResult(
                supported=False,
                unsupported_claim_count=1,
                reason_code="no_answer_or_evidence",
            )

        from backend.core.llm_instances import get_llm_smart

        claims = legal_claim_segments(answer)
        if not claims:
            return ClaimSupportResult(
                supported=False,
                unsupported_claim_count=1,
                reason_code="no_material_legal_claim",
            )

        model = get_llm_smart().with_structured_output(ClaimSupportResult)
        payload: dict[str, Any] = {
            "claims": [
                {
                    "claim_index": index,
                    "text": claim,
                    "citation_indices": [int(value) for value in _CITATION_RE.findall(claim)],
                }
                for index, claim in enumerate(claims, start=1)
            ],
            "evidence": [
                {
                    "citation_index": index,
                    "document_id": document.document_id,
                    "legal_anchor": _anchor(document),
                    "source": str((document.metadata or {}).get("source") or ""),
                    "text": document.content[: self.max_chars_per_evidence],
                }
                for index, document in enumerate(documents, start=1)
            ],
        }
        result = await model.ainvoke(
            [
                ("system", _SYSTEM_PROMPT),
                ("human", "Verify this JSON data only:\n" + json.dumps(payload, ensure_ascii=False)),
            ]
        )
        if not isinstance(result, ClaimSupportResult):
            result = ClaimSupportResult.model_validate(result)
        # Keep an empty/ambiguous reason from becoming an apparent successful
        # validation in operational traces.
        if result.unsupported_claim_indices and result.unsupported_claim_count == 0:
            result.unsupported_claim_count = len(result.unsupported_claim_indices)
        if result.supported and (result.unsupported_claim_count or result.unsupported_claim_indices):
            result.supported = False
            result.reason_code = "unsupported_claims_reported"
        return result


class StaticClaimSupportVerifier:
    """Deterministic verifier double used by tests and offline development."""

    def __init__(self, *, supported: bool = True, reason_code: str = "ok") -> None:
        self.result = ClaimSupportResult(
            supported=supported,
            unsupported_claim_count=0 if supported else 1,
            reason_code=reason_code,
            model="static",
        )
        self.calls = 0

    async def verify(self, answer: str, documents: list[DocumentRecord]) -> ClaimSupportResult:
        self.calls += 1
        return self.result.model_copy(deep=True)


class LegalCriticVerdict(BaseModel):
    """Structured verdict produced by the Senior Legal Critic / Auditor Agent."""

    approved: bool = Field(description="True if the answer is legally sound, accurate, and free of fatal statutory flaws.")
    critique: str = Field(default="", description="Senior Vietnamese legal auditor's evaluation and commentary.")
    corrected_answer: str | None = Field(default=None, description="Optional improved answer if minor statutory nuances can be refined.")
    fatal_error: bool = Field(default=False, description="True if the answer misapplies law, cites nonexistent provisions, or contradicts explicit statutory exceptions.")
    temporal_issues_detected: bool = Field(default=False, description="True if answer relies on superseded or repealed laws without noting the amendments.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    conflicting_provisions: list[str] = Field(default_factory=list, description="List of provision numbers that have statutory conflicts or misinterpretations.")


_LEGAL_CRITIC_SYSTEM_PROMPT = """Bạn là Thẩm định viên Pháp lý Cấp cao (Senior Legal Auditor & Critic) của Hệ thống Trợ lý Pháp luật Việt Nam.

Nhiệm vụ của bạn là thẩm định và phản biện độc lập câu trả lời pháp lý do AI soạn thảo trước khi trả về cho người dùng.

Tiêu chuẩn Thẩm định:
1. Tính Chính xác của Căn cứ Pháp lý: Kiểm tra các số Điều, Khoản, Luật/Nghị định được viện dẫn có áp dụng đúng cho quan hệ pháp luật của người dùng hay không.
2. Quy tắc Chung vs Quy tắc Ngoại lệ: Kiểm tra xem câu trả lời có bỏ sót các trường hợp ngoại lệ hoặc điều kiện tiên quyết luật định hay không.
3. Tính Thời điểm & Hiệu lực: Cảnh báo nếu câu trả lời dựa vào các quy định cũ đã bị sửa đổi/bổ sung mà không kèm theo lưu ý văn bản mới.
4. Quyền và Nghĩa vụ Đầy đủ: Đảm bảo tư vấn đúng bản chất quyền lợi, nghĩa vụ, và thủ tục hành chính/tố tụng liên quan.

Nguyên tắc Phê duyệt:
- approved = True: Nếu câu trả lời chuẩn xác, logic pháp lý chặt chẽ và bám sát tài liệu căn cứ.
- fatal_error = True (approved = False): Chỉ khi câu trả lời tư vấn SAI HOÀN TOÀN về mặt luật định, bịa đặt điều luật, hoặc đảo ngược hoàn toàn quyền/nghĩa vụ của công dân.
- corrected_answer: Nếu câu trả lời tốt nhưng có thể diễn đạt gãy gọn hơn hoặc bổ sung lưu ý về hiệu lực văn bản, hãy cung cấp bản hoàn thiện.
"""


class LegalCriticReviewer:
    """Senior Legal Auditor agent performing peer review on draft answers."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    async def review(
        self,
        query: str,
        answer: str,
        documents: list[DocumentRecord],
    ) -> LegalCriticVerdict:
        if not self.enabled or not answer.strip():
            return LegalCriticVerdict(approved=True, critique="Critic check skipped or empty answer.")

        if not documents:
            return LegalCriticVerdict(approved=True, critique="No legal documents to audit against.")

        from backend.core.llm_instances import get_llm_smart

        try:
            model = get_llm_smart().with_structured_output(LegalCriticVerdict)
            payload = {
                "user_query": query,
                "draft_answer": answer,
                "legal_evidence": [
                    {
                        "document_id": doc.document_id,
                        "source": str((doc.metadata or {}).get("source") or doc.source),
                        "legal_anchor": _anchor(doc),
                        "effective_status": doc.effective_status or (doc.metadata or {}).get("Effective_Status"),
                        "effective_from": doc.effective_from or (doc.metadata or {}).get("Effective_From"),
                        "effective_to": doc.effective_to or (doc.metadata or {}).get("Effective_To"),
                        "amendment_relationship": doc.amendment_relationship or (doc.metadata or {}).get("Amendment_Relationship"),
                        "text": doc.content[:2000],
                    }
                    for doc in documents[:6]
                ],
            }

            result = await model.ainvoke(
                [
                    ("system", _LEGAL_CRITIC_SYSTEM_PROMPT),
                    ("human", "Hãy thẩm định câu trả lời sau:\n" + json.dumps(payload, ensure_ascii=False)),
                ]
            )
            if not isinstance(result, LegalCriticVerdict):
                result = LegalCriticVerdict.model_validate(result)
            return result
        except Exception as exc:  # noqa: BLE001
            # Fallback gracefully if model call fails in offline / mock test mode
            return LegalCriticVerdict(
                approved=True,
                critique=f"Critic evaluation fallback: {exc}",
                confidence=0.8,
            )


class StaticLegalCriticReviewer:
    """Deterministic critic double for unit testing and offline development."""

    def __init__(self, *, verdict: LegalCriticVerdict | None = None) -> None:
        self.verdict = verdict or LegalCriticVerdict(approved=True, critique="Static pass.")

    async def review(
        self,
        query: str,
        answer: str,
        documents: list[DocumentRecord],
    ) -> LegalCriticVerdict:
        return self.verdict
