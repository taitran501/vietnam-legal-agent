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
import unicodedata
from typing import Any, Protocol

from pydantic import BaseModel, Field

from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.domain.verification import VerificationStatus, canonical_verification_status
from vietnam_legal_agent.tools.evidence import legal_claim_segments

_CITATION_RE = re.compile(r"\[(\d+)\]")


class ClaimSupportResult(BaseModel):
    """Sanitised result of the batch claim-to-evidence verification."""

    supported: bool
    unsupported_claim_count: int = Field(default=0, ge=0)
    unsupported_claim_indices: list[int] = Field(default_factory=list)
    reason_code: str = Field(default="ok", max_length=1000)
    verification_status: VerificationStatus = VerificationStatus.VERIFIED
    corrected_answer: str = Field(
        default="",
        max_length=12000,
        description=(
            "When unsupported claims can be removed or narrowed while preserving useful supported content, "
            "provide that concise corrected answer with valid evidence citations. Otherwise leave empty."
        ),
    )
    model: str = Field(default="", max_length=200)
    token_usage: dict[str, int] = Field(default_factory=dict)


class ClaimSupportVerifier(Protocol):
    async def verify(
        self,
        answer: str,
        documents: list[DocumentRecord],
        *,
        query: str = "",
    ) -> ClaimSupportResult: ...


_CONTEXTUAL_CLAIM_PREFIXES = (
    "do đó",
    "vì vậy",
    "như vậy",
    "theo đó",
    "theo quy định này",
    "theo điều này",
    "theo quy định trên",
    "theo điều khoản trên",
    "trên cơ sở đó",
    "với quy tắc này",
)


def _claim_segments_with_context(answer: str) -> list[str]:
    """Keep anaphoric legal conclusions with the sentence that limits them."""

    claims = legal_claim_segments(answer)
    contextual: list[str] = []
    for claim in claims:
        normalized = _CITATION_RE.sub("", claim).strip().casefold()
        if contextual and normalized.startswith(_CONTEXTUAL_CLAIM_PREFIXES):
            contextual[-1] = f"{contextual[-1]} {claim}"
        else:
            contextual.append(claim)
    return contextual


def claim_segments_for_verification(answer: str) -> list[str]:
    """Return the exact 1-based claim sequence used by the claim verifier."""

    return _claim_segments_with_context(answer) or ([answer.strip()] if answer.strip() else [])


_SYSTEM_PROMPT = """You verify whether each separate legal claim in the generated Vietnamese answer is
directly supported by and consistent with the provided legal evidence chunks. Return only the requested structured schema.

Evaluation Guidelines:
1. Evidence boundary: A claim is supported only when the evidence states it or it follows necessarily from a rule stated in the evidence and facts supplied in the query. Do not use general legal knowledge or plausible practice to fill missing rights, remedies, duties, procedures, deadlines, fees, or exceptions.
2. Separate claims: Evaluate every sentence and distinct legal proposition separately. One citation or supported sentence does not support other claims in the same paragraph.
3. Citation-bound evidence: For each claim, use only the evidence items listed in that claim's cited_evidence. Evidence that the answer did not cite for that claim cannot rescue it. At least one cited source must directly support every material part of the claim; if the claim has no cited evidence, it is unsupported.
4. Party roles: Check labels such as depositor/recipient, employer/employee, buyer/seller, claimant/respondent, or parent/custodian against the query and evidence. A duty imposed on one party does not automatically establish a separate right or remedy for another party.
5. Contextual application: Apply a stated rule to dates, locations, or other facts only when those facts are in the query and every necessary legal condition is evidenced. Do not assume facts from a typical scenario.
6. Conditions and exceptions: A claim is unsupported if it omits a condition or exception that changes when a right or duty applies. Equivalent paraphrases are acceptable; compare meaning, not matching words. When the evidence gives a general duty with an exception, do not infer that the exception is absent just because the user did not mention its facts; keep the outcome conditional if an unknown fact could change it for the facts supplied. Apply an explicit numeric or time threshold directly when the evidence and query provide both values. If a duty applies only from N days onward and the query states M days where M < N, the narrow claim that this threshold-based duty has not arisen is supported by the evidence; do not reject it for missing facts about an exception that cannot change the below-threshold result. Distinguish “this clause does not establish an entitlement on the stated facts” from “no other entitlement exists”; the latter needs evidence about other legal bases. Preserve any prerequisite that could still change the result, and do not withhold a useful partial answer merely because unrelated facts are missing.
7. Express source clauses: If a claim faithfully repeats or summarizes an explicit clause in the evidence, including a broad catch-all clause, treat it as supported only to the scope stated in that clause. Do not require the answer to enumerate details that the clause itself leaves open, and do not let the answer expand the clause beyond its wording.
8. Index contract: unsupported_claim_indices must contain the 1-based claim_index values from the input JSON, not zero-based array positions. They must identify the same claims described in reason_code.
9. Meaning of supported: supported=false means at least one material legal claim is not established by this evidence, whether or not it might be true under another law or source. Do not mark it supported merely because it sounds reasonable or is not contradicted.
10. Question scope: Use the user's question to check that each claim applies to the same actor, event, procedural stage, and requested outcome. A rule about a later change, appeal, enforcement step, or separate remedy does not answer a question about the initial decision or another stage, even if its wording is similar. Mark a materially off-scope claim unsupported and explain the stage mismatch.
11. Scope of the legal regime: Read the provision's heading, addressee, transaction type, status, and express conditions together. A rule limited to a particular business model, profession, contract type, product, or procedural posture cannot be generalized to all sellers, consumers, workers, or transactions. If the user has not established that they are in the named category, treat an unconditional answer as unsupported or state the category as a condition.
12. No invented prerequisites: Do not import a condition from a neighboring provision or a different scenario unless the cited text expressly requires it. When the evidence directly states a default for the case where parties did not agree, do not add a prior-agreement requirement from a separate rule. Evaluate cross-referenced evidence before rejecting a claim, and distinguish the default rule from rules for another case.
13. Context references: A sentence beginning with a reference such as "therefore", "accordingly", or "under this rule" depends on the preceding sentence. Evaluate it together with that antecedent and retain the antecedent's conditions; do not treat it as a new unconditional claim.
14. Internal consistency: Check the answer as a whole for claims that express the same legal effect with opposite conclusions or incompatible amounts. A later restatement does not become valid merely because it uses different words. If the answer contradicts itself, mark the conflicting claim unsupported and use corrected_answer to state the source's exact legal effect unambiguously.
15. Amounts and components: Read every monetary component and its arithmetic literally. Distinguish returning a principal amount from paying an additional amount; if the source requires both the original amount and an equal additional amount, the total is twice the original amount. Do not omit one component or reject an equivalent total described in the question. If the evidence does not establish a component or amount, say so rather than guessing.
16. Language: Answer in the user's language. When the question is in Vietnamese, a corrected_answer must be in Vietnamese.
17. Useful correction: If one or more claims are unsupported but the evidence still directly answers part of the question, fill corrected_answer with a short answer that preserves the supported substance and removes or narrows only the unsupported claims. Prefer stating the exact rule in the evidence (for example, the conduct a provision prohibits) over converting it into a broader right, remedy, or procedure. Keep factual conditions and attach citations from the supplied evidence. Leave corrected_answer empty only when no useful, supported answer can be made."""


def _anchor(document: DocumentRecord) -> str:
    metadata = document.metadata or {}
    return str(
        metadata.get("legal_anchor")
        or metadata.get("Parent_Dieu")
        or metadata.get("Dieu")
        or metadata.get("Điều")
        or ""
    )


def _normalise_verbatim_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", _CITATION_RE.sub("", text or "")).casefold()
    tokens = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    return " ".join(str(int(token)) if token.isdigit() else token for token in tokens)


def _claim_is_explicitly_stated(claim: str, documents: list[DocumentRecord]) -> bool:
    """Recognize a verbatim source clause that a semantic verifier may over-reject.

    For list claims with a qualifying heading, the assertion after the colon
    must occur in one source, and the heading's terms must also be represented
    there. This is a text-to-source match, not a legal-rule inference.
    """

    citation_indices = {int(value) for value in _CITATION_RE.findall(claim or "")}
    if not citation_indices:
        return False
    cited_documents = [
        document
        for index, document in enumerate(documents, start=1)
        if index in citation_indices
    ]
    if not cited_documents:
        return False

    claim_text = _CITATION_RE.sub("", claim or "").strip()
    _head, separator, body = claim_text.rpartition(":")
    candidates = [claim_text]
    if separator and body.strip():
        body_text = body.strip()
        if not re.match(r"[\"'“”‘’«»]", body_text):
            candidates.append(body_text)

    for document in cited_documents:
        source = _normalise_verbatim_text(document.content)
        for candidate in candidates:
            normalized = _normalise_verbatim_text(candidate)
            candidate_tokens = set(normalized.split())
            if len(candidate_tokens) < 5:
                continue
            if normalized in source:
                return True
            source_fragments = [
                _normalise_verbatim_text(fragment)
                for fragment in re.split(r"(?<=[.!?;])\s+|\n+", document.content)
                if fragment.strip()
            ]
            for fragment in source_fragments:
                fragment_tokens = set(fragment.split())
                token_coverage = len(candidate_tokens & fragment_tokens) / len(candidate_tokens)
                candidate_numbers = {token for token in candidate_tokens if token.isdigit()}
                if token_coverage < 0.85 or not candidate_numbers.issubset(fragment_tokens):
                    continue
                condition_tokens = candidate_tokens & {
                    "nếu", "trừ", "không", "chỉ", "phải", "được", "khi", "trong", "ít", "nhất"
                }
                if not condition_tokens.issubset(fragment_tokens):
                    continue
                return True
    return False


class StructuredClaimSupportVerifier:
    """One OpenAI structured-output call for the legal support decision."""

    def __init__(self, *, max_chars_per_evidence: int = 3000) -> None:
        self.max_chars_per_evidence = max(500, max_chars_per_evidence)

    async def verify(
        self,
        answer: str,
        documents: list[DocumentRecord],
        *,
        query: str = "",
    ) -> ClaimSupportResult:
        if not answer.strip() or not documents:
            return ClaimSupportResult(
                supported=False,
                unsupported_claim_count=1,
                reason_code="no_answer_or_evidence",
                verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            )

        claims = claim_segments_for_verification(answer)

        evidence_payload = [
            {
                "citation_index": index,
                "document_id": document.document_id,
                "legal_anchor": _anchor(document),
                "source": str((document.metadata or {}).get("source") or ""),
                "text": document.content[: self.max_chars_per_evidence],
            }
            for index, document in enumerate(documents, start=1)
        ]
        evidence_by_index = {
            item["citation_index"]: item
            for item in evidence_payload
        }
        payload: dict[str, Any] = {
            "user_question": str(query or "").strip()[:3000],
            "claims": [
                {
                    "claim_index": index,
                    "text": claim,
                    "citation_indices": [int(value) for value in _CITATION_RE.findall(claim)],
                    "cited_evidence": [
                        evidence_by_index[citation_index]
                        for citation_index in dict.fromkeys(
                            int(value) for value in _CITATION_RE.findall(claim)
                        )
                        if citation_index in evidence_by_index
                    ],
                }
                for index, claim in enumerate(claims, start=1)
            ],
        }
        try:
            from vietnam_legal_agent.infra.llm_instances import get_llm_smart

            model = get_llm_smart().with_structured_output(ClaimSupportResult)
            result = await model.ainvoke(
                [
                    ("system", _SYSTEM_PROMPT),
                    ("human", "Verify this JSON data only:\n" + json.dumps(payload, ensure_ascii=False)),
                ]
            )
            if not isinstance(result, ClaimSupportResult):
                result = ClaimSupportResult.model_validate(result)
            reason_claim = re.search(r"\bclaim\s+#?\s*(\d+)\b", result.reason_code, flags=re.IGNORECASE)
            if (
                reason_claim
                and len(result.unsupported_claim_indices) == 1
                and result.unsupported_claim_indices[0] == int(reason_claim.group(1)) - 1
                and 1 <= int(reason_claim.group(1)) <= len(claims)
            ):
                # Some structured responses describe the correct 1-based
                # claim in prose but return its zero-based list offset.
                result.unsupported_claim_indices = [int(reason_claim.group(1))]
            explicitly_supported = {
                index
                for index, claim in enumerate(claims, start=1)
                if _claim_is_explicitly_stated(claim, documents)
            }
            removed_indices = set(result.unsupported_claim_indices) & explicitly_supported
            if removed_indices:
                result.unsupported_claim_indices = [
                    index for index in result.unsupported_claim_indices if index not in removed_indices
                ]
                result.unsupported_claim_count = max(
                    len(result.unsupported_claim_indices),
                    result.unsupported_claim_count - len(removed_indices),
                )
                if result.unsupported_claim_count == 0 and not result.unsupported_claim_indices:
                    result.supported = True
                    result.reason_code = "explicit_source_match"
                    result.verification_status = VerificationStatus.VERIFIED
            if result.unsupported_claim_indices and result.unsupported_claim_count == 0:
                result.unsupported_claim_count = len(result.unsupported_claim_indices)
            if result.supported and (result.unsupported_claim_count or result.unsupported_claim_indices):
                result.supported = False
                result.reason_code = "unsupported_claims_reported"
            result.verification_status = canonical_verification_status(
                result.verification_status,
                supported=result.supported,
                reason_code=result.reason_code,
            )
            result.supported = result.verification_status is VerificationStatus.VERIFIED
            return result
        except Exception:  # noqa: BLE001 - a legal verifier outage must stop delivery
            return ClaimSupportResult(
                supported=False,
                unsupported_claim_count=1,
                reason_code="verifier_fallback",
                verification_status=VerificationStatus.VERIFICATION_UNAVAILABLE,
            )


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

    async def verify(
        self,
        answer: str,
        documents: list[DocumentRecord],
        *,
        query: str = "",
    ) -> ClaimSupportResult:
        _ = query
        self.calls += 1
        return self.result.model_copy(deep=True)


class LegalCriticVerdict(BaseModel):
    """Structured verdict produced by the Senior Legal Critic / Auditor Agent."""

    approved: bool = Field(
        description=(
            "True when the answer contains no materially false legal proposition and is appropriately limited "
            "to the evidence; missing optional detail alone does not require rejection."
        )
    )
    critique: str = Field(default="", description="Senior Vietnamese legal auditor's evaluation and commentary.")
    corrected_answer: str | None = Field(default=None, description="Optional improved answer if minor statutory nuances can be refined.")
    materially_nonresponsive: bool = Field(
        default=False,
        description=(
            "True only when the answer addresses a different legal question, procedural stage, or factual scenario "
            "than the user asked. Omitting optional details alone is not materially nonresponsive."
        ),
    )
    fatal_error: bool = Field(
        default=False,
        description=(
            "True only when you identify a specific materially false legal proposition, fabricated provision, "
            "or contradiction of an explicit statutory rule. Incompleteness or an unanswered sub-question is not fatal."
        ),
    )
    temporal_issues_detected: bool = Field(default=False, description="True if answer relies on superseded or repealed laws without noting the amendments.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    conflicting_provisions: list[str] = Field(default_factory=list, description="List of provision numbers that have statutory conflicts or misinterpretations.")
    reason_code: str = Field(default="ok", max_length=1000)
    verification_status: VerificationStatus = VerificationStatus.VERIFIED


_LEGAL_CRITIC_SYSTEM_PROMPT = """Bạn là Thẩm định viên Pháp lý Cấp cao (Senior Legal Auditor & Critic) của Hệ thống Trợ lý Pháp luật Việt Nam.

Nhiệm vụ của bạn là thẩm định và phản biện độc lập câu trả lời pháp lý do AI soạn thảo trước khi trả về cho người dùng.

Tiêu chuẩn Thẩm định:
1. Tính Chính xác của Căn cứ Pháp lý: Kiểm tra các số Điều, Khoản, Luật/Nghị định được viện dẫn có áp dụng đúng cho quan hệ pháp luật của người dùng hay không.
2. Quy tắc Chung vs Quy tắc Ngoại lệ: Kiểm tra xem câu trả lời có bỏ sót các trường hợp ngoại lệ hoặc điều kiện tiên quyết luật định hay không.
3. Tính Thời điểm & Hiệu lực: Cảnh báo nếu câu trả lời dựa vào các quy định cũ đã bị sửa đổi/bổ sung mà không kèm theo lưu ý văn bản mới.
4. Quyền và Nghĩa vụ Đầy đủ: Đảm bảo tư vấn đúng bản chất quyền lợi, nghĩa vụ, và thủ tục hành chính/tố tụng liên quan.

Nguyên tắc Phê duyệt:
- approved = True chỉ khi mọi nhận định pháp lý quan trọng được tài liệu cung cấp hỗ trợ trực tiếp hoặc là hệ quả tất yếu của quy tắc trong tài liệu và dữ kiện người dùng nêu. Kiến thức pháp luật bên ngoài hoặc điều thường xảy ra không thay thế căn cứ trong payload.
- fatal_error = True (approved = False): Chỉ khi câu trả lời tư vấn SAI HOÀN TOÀN về mặt luật định, bịa đặt điều luật, hoặc đảo ngược hoàn toàn quyền/nghĩa vụ của công dân.
- Không coi việc câu trả lời chưa bao quát mọi quyền, ngoại lệ hoặc thủ tục là lỗi pháp lý nghiêm trọng nếu câu trả lời không đưa ra nhận định sai. Nếu tài liệu được truy xuất chưa đủ để kết luận, một câu trả lời nêu rõ giới hạn bằng chứng và không khẳng định vượt quá nguồn phải được approved = True, fatal_error = False.
- Với ngưỡng số lượng hoặc thời gian được nêu rõ trong tài liệu, hãy áp dụng phép so sánh trực tiếp khi câu hỏi cũng cung cấp giá trị cần so sánh. Giới hạn kết luận vào nghĩa vụ gắn với ngưỡng đó, nêu điều kiện có thể làm thay đổi kết luận và giữ lại phần trả lời được nguồn hỗ trợ.
- Ví dụ logic: nếu nghĩa vụ chỉ phát sinh từ N ngày trở lên và câu hỏi nêu M ngày với M < N, nhận định rằng nghĩa vụ gắn với ngưỡng đó chưa phát sinh được nguồn hỗ trợ; không suy ra rằng mọi biện pháp riêng khác đều không áp dụng.
- Phân biệt câu “điều khoản này chưa xác lập khoản phải trả trên dữ kiện đã nêu” với câu “không có bất kỳ quyền lợi nào khác”; câu sau cần bằng chứng riêng về các căn cứ khác.
- Không suy ra một quyền hoặc biện pháp khắc phục cụ thể chỉ từ nghĩa vụ của chủ thể khác hay từ nguyên tắc chung. Nếu nhận định quan trọng vượt quá tài liệu, đặt approved = false, fatal_error = false, verification_status = unsupported_claim; dùng corrected_answer để lược bỏ phần không được chứng minh và nêu giới hạn nguồn nếu cần.
- Kiểm tra tính nhất quán của toàn câu trả lời: không thể phủ nhận một kết quả rồi mô tả lại chính kết quả đó bằng các thành phần tương đương. Nếu có mâu thuẫn về kết luận hoặc số tiền, hãy nêu rõ nội dung nguồn hỗ trợ trong corrected_answer.
- Đọc đầy đủ từng cấu phần của khoản tiền và phép tính: nếu nguồn yêu cầu hoàn khoản gốc và trả thêm một khoản bằng với khoản gốc, đó là tổng gấp đôi; không bỏ khoản trả thêm hoặc phủ nhận cách diễn đạt tương đương. corrected_answer phải cùng ngôn ngữ với câu hỏi.
- Phải đối chiếu câu trả lời với đúng câu hỏi, giai đoạn thủ tục và tình huống người dùng nêu. Một quy tắc có thật nhưng chỉ áp dụng cho giai đoạn khác hoặc một vấn đề gần giống không trả lời đúng câu hỏi. Khi tài liệu đã có căn cứ trực tiếp, hãy đưa bản trả lời đúng vào corrected_answer và đặt materially_nonresponsive = true; không dùng cờ này chỉ vì thiếu chi tiết phụ.
- Đối chiếu phạm vi của chủ thể, loại giao dịch, ngành nghề, tư cách pháp lý và điều kiện được nêu trong tiêu đề/toàn văn điều khoản. Không biến quy định chỉ áp dụng cho một nhóm giao dịch hoặc một loại chủ thể thành quyền/nghĩa vụ chung của mọi người bán, người tiêu dùng, người lao động hoặc hợp đồng.
- Không nhập một điều kiện từ điều khoản gần kề hoặc tình huống khác nếu căn cứ được cung cấp không yêu cầu điều kiện đó. Nếu điều khoản nêu trực tiếp quy tắc mặc định khi các bên không thỏa thuận, hãy áp dụng đúng quy tắc mặc định ấy; không đòi phải có một thỏa thuận khác trước đó trừ khi văn bản nói rõ.
- Không đòi câu trả lời suy đoán nội dung còn thiếu từ nguồn hoặc liệt kê mọi hệ quả pháp lý ngoài phạm vi câu hỏi. Chỉ bác bỏ khi có nhận định pháp lý cụ thể không được nguồn hỗ trợ hoặc trái với nguồn; nếu cần sửa một điểm cụ thể, hãy dùng corrected_answer.
- Với câu hỏi có/không, corrected_answer nên tập trung vào kết luận và điều kiện trọng yếu được nguồn hỗ trợ. Không thêm checklist thủ tục, danh sách giấy tờ hoặc nhận định chứng cứ nếu câu hỏi không yêu cầu và payload không có căn cứ trực tiếp cho các chi tiết đó.
- Đối chiếu vai trò của các bên với đúng định nghĩa trong nguồn. Không tự suy ra ai là bên đặt cọc/bên nhận đặt cọc, người lao động/người sử dụng lao động hoặc bên có quyền/bên có nghĩa vụ chỉ từ tình huống thường gặp.
- corrected_answer: Nếu câu trả lời tốt nhưng có thể diễn đạt gãy gọn hơn hoặc bổ sung lưu ý về hiệu lực văn bản, hãy cung cấp bản hoàn thiện. Mỗi nhận định pháp lý trong bản sửa phải có citation [n] trỏ đúng thứ tự legal_evidence; nếu không thể gắn citation hợp lệ cho từng nhận định thì để corrected_answer rỗng.
- Chế độ source_version_only: Khi payload đánh dấu true, bộ bằng chứng chỉ giới hạn ở một phiên bản nguồn và người dùng không hỏi hiệu lực hiện hành. Đối chiếu câu trả lời với chính nguồn đó; yêu cầu nêu rõ căn cứ được trích dẫn và chưa xác minh hiệu lực hiện hành. Không từ chối chỉ vì có văn bản sửa đổi sau này. Vẫn từ chối nếu câu trả lời mô tả sai nội dung nguồn hoặc khẳng định quá phạm vi nguồn.
- Khi source_version_only là false, hãy thẩm định các nhận định về hiệu lực như bình thường. Nếu evidence chưa xác nhận hiệu lực hiện hành thì câu trả lời nêu rõ chưa xác minh được hiệu lực không phải lỗi pháp lý.
- Nếu payload có `claim_verifier_feedback`, hãy dùng nó như các nhận định cần kiểm tra lại: đối chiếu từng nhận định với đúng tài liệu và dữ kiện câu hỏi, rồi sửa hoặc lược bỏ phần không được hỗ trợ trong `corrected_answer`. Feedback không thay thế việc đọc nguồn, nhưng không được bỏ qua nhận định bị gắn cờ. Giữ lại mọi phần khác đã được nguồn hỗ trợ; nếu nguồn trả lời trực tiếp một quy tắc, hãy nêu quy tắc đó trong phạm vi chính xác của nguồn thay vì từ chối toàn bộ câu hỏi.
- Mỗi tài liệu có `citation_index` giữ nguyên số trích dẫn trong câu trả lời. Nếu viết `corrected_answer`, chỉ dùng đúng các số `citation_index` được cung cấp; không đánh lại số theo thứ tự tài liệu trong payload.
"""


def _critic_evidence_documents(
    answer: str,
    documents: list[DocumentRecord],
    *,
    limit: int = 6,
) -> list[tuple[int, DocumentRecord]]:
    """Keep cited evidence in the critic's bounded payload before other results."""

    selected_indices: list[int] = []
    for raw_index in _CITATION_RE.findall(answer):
        index = int(raw_index) - 1
        if 0 <= index < len(documents) and index not in selected_indices:
            selected_indices.append(index)
    selected_indices.extend(index for index in range(len(documents)) if index not in selected_indices)
    return [(index + 1, documents[index]) for index in selected_indices[:limit]]


class LegalCriticReviewer:
    """Senior Legal Auditor agent performing peer review on draft answers."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    async def review(
        self,
        query: str,
        answer: str,
        documents: list[DocumentRecord],
        *,
        source_version_only: bool = False,
        verification_feedback: dict[str, Any] | None = None,
    ) -> LegalCriticVerdict:
        if not self.enabled or not answer.strip():
            return LegalCriticVerdict(
                approved=False,
                fatal_error=True,
                critique="Critic check unavailable.",
                reason_code="critic_disabled_or_empty_answer",
                verification_status=VerificationStatus.VERIFICATION_UNAVAILABLE,
            )

        if not documents:
            return LegalCriticVerdict(
                approved=False,
                fatal_error=True,
                critique="No legal documents to audit against.",
                reason_code="insufficient_evidence",
                verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            )

        try:
            from vietnam_legal_agent.infra.llm_instances import get_llm_smart

            model = get_llm_smart().with_structured_output(LegalCriticVerdict)
            selected_evidence = _critic_evidence_documents(answer, documents)
            payload = {
                "user_query": query,
                "draft_answer": answer,
                "source_version_only": source_version_only,
                "claim_verifier_feedback": verification_feedback or {},
                "legal_evidence": [
                    {
                        "citation_index": citation_index,
                        "document_id": doc.document_id,
                        "source": str((doc.metadata or {}).get("source") or doc.source),
                        "legal_anchor": _anchor(doc),
                        "effective_status": doc.effective_status or (doc.metadata or {}).get("Effective_Status"),
                        "effective_from": doc.effective_from or (doc.metadata or {}).get("Effective_From"),
                        "effective_to": doc.effective_to or (doc.metadata or {}).get("Effective_To"),
                        "amendment_relationship": doc.amendment_relationship or (doc.metadata or {}).get("Amendment_Relationship"),
                        "text": doc.content[:2000],
                    }
                    for citation_index, doc in selected_evidence
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
            result.verification_status = canonical_verification_status(
                result.verification_status,
                supported=result.approved and not result.fatal_error,
                reason_code=result.reason_code,
            )
            if result.verification_status is VerificationStatus.VERIFICATION_UNAVAILABLE:
                result.approved = False
                result.fatal_error = True
                result.reason_code = result.reason_code if result.reason_code != "ok" else "critic_unavailable"
            elif result.verification_status is VerificationStatus.INSUFFICIENT_EVIDENCE:
                result.approved = False
                result.fatal_error = True
                result.reason_code = result.reason_code if result.reason_code != "ok" else "critic_verification_rejected"
            elif result.verification_status is VerificationStatus.UNSUPPORTED_CLAIM:
                result.approved = False
                result.reason_code = result.reason_code if result.reason_code != "ok" else "critic_review_concern"
            elif result.approved and not result.fatal_error:
                result.verification_status = VerificationStatus.VERIFIED
            return result
        except Exception:  # noqa: BLE001 - a critic outage must stop legal delivery
            return LegalCriticVerdict(
                approved=False,
                fatal_error=True,
                critique="Critic evaluation unavailable.",
                reason_code="critic_unavailable",
                verification_status=VerificationStatus.VERIFICATION_UNAVAILABLE,
            )


class StaticLegalCriticReviewer:
    """Deterministic critic double for unit testing and offline development."""

    def __init__(self, *, verdict: LegalCriticVerdict | None = None) -> None:
        self.verdict = verdict or LegalCriticVerdict(approved=True, critique="Static pass.")
        self.source_version_only_calls: list[bool] = []

    async def review(
        self,
        query: str,
        answer: str,
        documents: list[DocumentRecord],
        *,
        source_version_only: bool = False,
        verification_feedback: dict[str, Any] | None = None,
    ) -> LegalCriticVerdict:
        self.source_version_only_calls.append(source_version_only)
        _ = verification_feedback
        return self.verdict
