from __future__ import annotations

import pytest

from vietnam_legal_agent.agent.guardrails import AgentGuardrails
from vietnam_legal_agent.domain.legal import explicit_anchors, parse_required_anchors
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.domain.routes import ROUTE_SPECS, RouteType
from vietnam_legal_agent.domain.v4 import RetrievalRequest
from vietnam_legal_agent.domain.verification import VerificationPolicy, VerificationStatus
from vietnam_legal_agent.tools.verifier import (
    ClaimSupportResult,
    LegalCriticReviewer,
    LegalCriticVerdict,
    StaticLegalCriticReviewer,
    StructuredClaimSupportVerifier,
)


def _document() -> DocumentRecord:
    return DocumentRecord(
        content="Điều 25 quy định thời gian thử việc và các điều kiện thực hiện. " * 8,
        document_id="labor-25",
        source="legal",
        metadata={"legal_anchor": "Điều 25", "source": "Bộ luật Lao động 2019"},
    )


def test_route_matrix_owns_verification_policy() -> None:
    assert ROUTE_SPECS[RouteType.LEGAL_LOOKUP].verification_policy is VerificationPolicy.LEGAL_CORPUS
    assert ROUTE_SPECS[RouteType.LEGAL_LOOKUP].max_evidence == 8
    assert ROUTE_SPECS[RouteType.CASE_ASSESSMENT].verification_policy is VerificationPolicy.LEGAL_CORPUS
    assert ROUTE_SPECS[RouteType.COMPLIANCE_CHECKLIST].verification_policy is VerificationPolicy.LEGAL_CORPUS
    assert ROUTE_SPECS[RouteType.RESEARCH_WEB].verification_policy is VerificationPolicy.WEB
    assert ROUTE_SPECS[RouteType.CHITCHAT].verification_policy is VerificationPolicy.NONE
    assert ROUTE_SPECS[RouteType.OUT_OF_SCOPE].verification_policy is VerificationPolicy.NONE


def test_required_anchor_parser_deduplicates_and_reports_invalid_values() -> None:
    parsed, invalid = parse_required_anchors(["Điều 25", "Điều 25", "not-an-anchor"])

    assert [anchor.key() for anchor in parsed] == ["Điều 25"]
    assert invalid == ["not-an-anchor"]


def test_required_anchor_parser_supports_appendix_addresses_and_preserves_document_scope() -> None:
    parsed, invalid = parse_required_anchors(["Nghị định 145/2020/NĐ-CP Phụ lục I"])

    assert invalid == []
    assert [anchor.key() for anchor in parsed] == ["145/2020/NĐ-CP | Phụ lục I"]
    combined = explicit_anchors("Điều 78 và Phụ lục XXII")
    assert [anchor.appendix for anchor in combined if anchor.appendix] == ["Phụ lục XXII"]


@pytest.mark.asyncio
async def test_retrieval_boundary_rejects_unparseable_required_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import vietnam_legal_agent.config

    monkeypatch.setattr(
        vietnam_legal_agent.config,
        "get_settings",
        lambda: type("SettingsDouble", (), {"enable_official_delta_retrieval": False})(),
    )
    from vietnam_legal_agent.tools.retrieval import RequiredAnchorParseError, UniversalLegalRetrievalGateway

    with pytest.raises(RequiredAnchorParseError, match="required_anchor_parse_failed"):
        await UniversalLegalRetrievalGateway().legal(
            RetrievalRequest(route="case_assessment", query="chấm dứt hợp đồng lao động", required_anchors=["???"])
        )


@pytest.mark.asyncio
async def test_guardrail_missing_legal_dependencies_fails_closed() -> None:
    valid, reason, _fallback, _citations = await AgentGuardrails.check_output(
        "Theo Điều 25 [1].",
        [_document()],
        require_evidence=True,
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        enforce_legal_safety_circuit_breaker=True,
    )

    assert valid is False
    assert reason == VerificationStatus.VERIFICATION_UNAVAILABLE.value


@pytest.mark.asyncio
async def test_structured_verifier_exception_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenModel:
        def with_structured_output(self, _schema):
            raise RuntimeError("offline")

    import vietnam_legal_agent.infra.llm_instances

    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: _BrokenModel())
    result = await StructuredClaimSupportVerifier().verify("Theo Điều 25 [1].", [_document()])

    assert result.supported is False
    assert result.verification_status is VerificationStatus.VERIFICATION_UNAVAILABLE
    assert result.reason_code == "verifier_fallback"


@pytest.mark.asyncio
async def test_unsegmented_legal_assertion_is_still_sent_to_claim_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CapturingModel:
        def __init__(self) -> None:
            self.payload = ""

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, messages):
            self.payload = messages[1][1]
            return {
                "supported": False,
                "unsupported_claim_count": 1,
                "reason_code": "unsupported_claim",
            }

    import vietnam_legal_agent.infra.llm_instances

    model = _CapturingModel()
    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: model)
    answer = "Người điều khiển xe máy không đội mũ sẽ bị phạt 200.000 đồng [1]."

    result = await StructuredClaimSupportVerifier().verify(answer, [_document()])

    assert "bị phạt 200.000 đồng" in model.payload
    assert result.supported is False
    assert result.verification_status is VerificationStatus.UNSUPPORTED_CLAIM


@pytest.mark.asyncio
async def test_structured_verifier_receives_original_question_for_stage_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CapturingModel:
        payload = ""
        system_prompt = ""

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, messages):
            self.system_prompt = messages[0][1]
            self.payload = messages[1][1]
            return {"supported": True, "reason_code": "ok"}

    import vietnam_legal_agent.infra.llm_instances

    model = _CapturingModel()
    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: model)
    question = "Ly hôn, tòa quyết định ban đầu ai trực tiếp nuôi con dựa vào yếu tố nào?"

    result = await StructuredClaimSupportVerifier().verify(
        "Tòa xem xét điều kiện chăm sóc con [1].",
        [_document()],
        query=question,
    )

    assert result.supported is True
    assert '"user_question": "' + question + '"' in model.payload
    assert "procedural stage" in model.system_prompt
    assert "Scope of the legal regime" in model.system_prompt
    assert "Citation-bound evidence" in model.system_prompt
    assert "No invented prerequisites" in model.system_prompt
    assert "Context references" in model.system_prompt
    assert "Internal consistency" in model.system_prompt
    assert "Amounts and components" in model.system_prompt
    assert "the total is twice the original amount" in model.system_prompt
    assert "a corrected_answer must be in Vietnamese" in model.system_prompt
    assert "do not infer that the exception is absent just because" in model.system_prompt
    assert "Apply an explicit numeric or time threshold directly" in model.system_prompt
    assert "threshold-based duty has not arisen" in model.system_prompt
    assert "the narrow claim that this threshold-based duty has not arisen is supported" in model.system_prompt
    assert "this clause does not establish an entitlement on the stated facts" in model.system_prompt
    assert "M < N" in model.system_prompt


@pytest.mark.asyncio
async def test_verifier_exposes_only_claim_citations_and_does_not_rescue_with_uncited_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CapturingRejectingModel:
        def __init__(self) -> None:
            self.payload: dict[str, object] = {}

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, messages):
            import json

            self.payload = json.loads(messages[1][1].partition("\n")[2])
            return {
                "supported": False,
                "unsupported_claim_count": 1,
                "unsupported_claim_indices": [1],
                "reason_code": "claim 1 has no support in its citation",
            }

    cited = DocumentRecord(
        content="Điều 68 quy định việc hoàn trả trong trách nhiệm bồi thường của Nhà nước.",
        document_id="unrelated-cited-source",
        source="legal",
        metadata={"legal_anchor": "Điều 68"},
    )
    uncited = DocumentRecord(
        content="Tiền lương làm thêm giờ vào ngày thường ít nhất bằng 150% tiền lương giờ thực trả.",
        document_id="relevant-but-uncited-source",
        source="legal",
        metadata={"legal_anchor": "Điều 98"},
    )
    import vietnam_legal_agent.infra.llm_instances

    model = _CapturingRejectingModel()
    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: model)

    result = await StructuredClaimSupportVerifier().verify(
        "Tiền làm thêm giờ vào ngày thường ít nhất bằng 150% tiền lương giờ thực trả [1].",
        [cited, uncited],
    )

    assert result.supported is False
    claim = model.payload["claims"][0]
    assert claim["citation_indices"] == [1]
    assert [item["document_id"] for item in claim["cited_evidence"]] == ["unrelated-cited-source"]


@pytest.mark.asyncio
async def test_verifier_keeps_anaphoric_legal_conclusion_with_its_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CapturingModel:
        payload = ""

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, messages):
            import json

            self.payload = json.loads(messages[1][1].partition("\n")[2])
            return {"supported": True, "reason_code": "ok"}

    import vietnam_legal_agent.infra.llm_instances

    model = _CapturingModel()
    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: model)
    answer = (
        "Nếu bên có nghĩa vụ chậm trả tiền thì phải trả lãi trên số tiền chậm trả [1]. "
        "Do đó, bên vay phải trả khoản lãi này."
    )

    await StructuredClaimSupportVerifier().verify(
        answer,
        [_document()],
        query="Khoản vay quá hạn có phải trả lãi không?",
    )

    assert len(model.payload["claims"]) == 1
    assert "Nếu bên có nghĩa vụ chậm trả tiền" in model.payload["claims"][0]["text"]
    assert "Do đó, bên vay phải trả khoản lãi này" in model.payload["claims"][0]["text"]


@pytest.mark.asyncio
async def test_verbatim_source_clause_is_not_rejected_as_too_general(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _OverRejectingModel:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return {
                "supported": False,
                "unsupported_claim_count": 1,
                "unsupported_claim_indices": [1],
                "reason_code": "Claim 2 is unsupported because the catch-all does not list every right.",
            }

    import vietnam_legal_agent.infra.llm_instances

    source = DocumentRecord(
        content=(
            "Điều 115. Quyền của cổ đông phổ thông. Cổ đông hoặc nhóm cổ đông sở hữu từ "
            "05% tổng số cổ phần phổ thông trở lên hoặc một tỷ lệ khác nhỏ hơn theo Điều lệ "
            "có quyền sau đây: d) Quyền khác theo quy định của Luật này và Điều lệ công ty."
        ),
        document_id="company-law-115",
        source="legal",
        metadata={"legal_anchor": "Điều 115"},
    )
    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: _OverRejectingModel())
    answer = (
        "Cổ đông hoặc nhóm cổ đông sở hữu từ 5% tổng số cổ phần phổ thông trở lên có quyền:\n"
        "1. Yêu cầu triệu tập họp Đại hội đồng cổ đông theo điều kiện luật định [1]\n"
        "2. Quyền khác theo quy định của Luật này và Điều lệ công ty [1]."
    )

    result = await StructuredClaimSupportVerifier().verify(answer, [source])

    assert result.supported is True
    assert result.unsupported_claim_count == 0
    assert result.unsupported_claim_indices == []
    assert result.reason_code == "explicit_source_match"


@pytest.mark.asyncio
async def test_verbatim_quote_does_not_rescue_an_unsupported_claim_introducing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RejectingModel:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return {
                "supported": False,
                "unsupported_claim_count": 1,
                "unsupported_claim_indices": [1],
                "reason_code": "Claim 1 applies a third-party property-return rule to a seller refund.",
                "verification_status": "unsupported_claim",
            }

    import vietnam_legal_agent.infra.llm_instances

    source = DocumentRecord(
        content=(
            'Điều 582. Quyền yêu cầu người thứ ba hoàn trả. '
            '"Trường hợp người chiếm hữu, người sử dụng tài sản mà không có căn cứ pháp luật '
            'đã giao tài sản cho người thứ ba thì khi bị chủ sở hữu, chủ thể có quyền khác '
            'đối với tài sản yêu cầu hoàn trả, người thứ ba có nghĩa vụ hoàn trả tài sản đó".'
        ),
        document_id="civil-code-582",
        source="legal",
        metadata={"legal_anchor": "Điều 582"},
    )
    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: _RejectingModel())
    answer = (
        'Bạn có quyền yêu cầu hoàn trả tiền đã thanh toán nếu bên bán không giao hàng theo thỏa thuận, '
        'theo Điều 582 Bộ luật Dân sự: "Trường hợp người chiếm hữu, người sử dụng tài sản mà không có '
        'căn cứ pháp luật đã giao tài sản cho người thứ ba thì khi bị chủ sở hữu, chủ thể có quyền khác '
        'đối với tài sản yêu cầu hoàn trả, người thứ ba có nghĩa vụ hoàn trả tài sản đó" [1].'
    )

    result = await StructuredClaimSupportVerifier().verify(answer, [source])

    assert result.supported is False
    assert result.verification_status is VerificationStatus.UNSUPPORTED_CLAIM


@pytest.mark.asyncio
async def test_verifier_reconciles_zero_based_index_for_supported_condition_paraphrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _OverRejectingModel:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return {
                "supported": False,
                "unsupported_claim_count": 1,
                "unsupported_claim_indices": [1],
                "reason_code": "Claim 2 is unsupported because it omits the child's age condition.",
            }

    import vietnam_legal_agent.infra.llm_instances

    source = DocumentRecord(
        content=(
            "Điều 81. Việc trông nom, chăm sóc, nuôi dưỡng, giáo dục con sau khi ly hôn. "
            "Con của vợ chồng được giao cho một bên trực tiếp nuôi, căn cứ vào quyền lợi về mọi mặt "
            "của con; nếu con từ đủ 07 tuổi trở lên thì phải xem xét nguyện vọng của con."
        ),
        document_id="family-law-81",
        source="legal",
        metadata={"legal_anchor": "Điều 81"},
    )
    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: _OverRejectingModel())
    answer = (
        "Tòa án căn cứ vào các yếu tố sau khi ly hôn:\n"
        "1. Nếu cha mẹ không thỏa thuận được, Tòa án căn cứ vào quyền lợi mọi mặt của con [1].\n"
        "2. Nếu con từ đủ 07 tuổi trở lên, Tòa án phải xem xét nguyện vọng của con [1]."
    )

    result = await StructuredClaimSupportVerifier().verify(answer, [source])

    assert result.supported is True
    assert result.reason_code == "explicit_source_match"
    assert result.unsupported_claim_indices == []


@pytest.mark.asyncio
async def test_claim_verifier_receives_each_numbered_list_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CapturingModel:
        def __init__(self) -> None:
            self.payload: dict[str, object] = {}

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, messages):
            import json

            self.payload = json.loads(messages[1][1].removeprefix("Verify this JSON data only:\n"))
            return {"supported": True, "unsupported_claim_count": 0, "reason_code": "ok"}

    import vietnam_legal_agent.infra.llm_instances

    model = _CapturingModel()
    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: model)
    answer = (
        "Các quyền cơ bản gồm:\n"
        "1. Được bảo đảm an toàn về tính mạng và sức khỏe [1]\n"
        "2. Được cung cấp thông tin đầy đủ về hàng hóa [1]\n"
        "3. Lựa chọn hàng hóa, dịch vụ [1]\n"
        "4. Góp ý kiến với tổ chức kinh doanh [1]\n"
        "5. Tham gia xây dựng chính sách bảo vệ người tiêu dùng [1]\n"
        "6. Yêu cầu bồi thường khi hàng hóa có khuyết tật [1]\n"
        "7. Khiếu nại, tố cáo, khởi kiện [1]\n"
        "8. Được tư vấn, hỗ trợ [1]\n"
        "9. Được bảo vệ khi sử dụng dịch vụ công [1]\n"
        "10. Thành lập hoặc tham gia tổ chức bảo vệ người tiêu dùng [1]\n"
        "11. Quyền khác theo quy định của pháp luật [1]"
    )

    result = await StructuredClaimSupportVerifier().verify(answer, [_document()])

    assert result.supported is True
    claims = model.payload["claims"]
    assert isinstance(claims, list)
    assert len(claims) == 11
    assert all(item["citation_indices"] == [1] for item in claims)


@pytest.mark.asyncio
async def test_legacy_no_evidence_reason_is_not_promoted_to_supported() -> None:
    class _LegacyVerifier:
        async def verify(
            self,
            _answer: str,
            _documents: list[DocumentRecord],
            *,
            query: str = "",
        ) -> ClaimSupportResult:
            _ = query
            return ClaimSupportResult(supported=False, reason_code="no_evidence_for_claims")

    valid, reason, _fallback, _citations = await AgentGuardrails.check_output(
        "Theo Điều 25 [1].",
        [_document()],
        require_evidence=True,
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        claim_verifier=_LegacyVerifier(),
        critic_reviewer=StaticLegalCriticReviewer(),
        enforce_legal_safety_circuit_breaker=True,
    )

    assert valid is False
    assert reason == "claim_support_insufficient_evidence"


@pytest.mark.asyncio
async def test_critic_disabled_or_empty_is_unavailable() -> None:
    disabled = await LegalCriticReviewer(enabled=False).review("q", "Theo [1].", [_document()])
    empty = await LegalCriticReviewer().review("q", "", [_document()])

    for verdict in (disabled, empty):
        assert verdict.approved is False
        assert verdict.fatal_error is True
        assert verdict.verification_status is VerificationStatus.VERIFICATION_UNAVAILABLE


@pytest.mark.asyncio
async def test_critic_legacy_unavailable_reason_is_not_promoted_to_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LegacyCriticModel:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return {"approved": True, "reason_code": "critic_unavailable"}

    monkeypatch.setattr(
        "vietnam_legal_agent.infra.llm_instances.get_llm_smart",
        lambda: _LegacyCriticModel(),
    )
    verdict = await LegalCriticReviewer().review("q", "Theo Điều 25 [1].", [_document()])

    assert verdict.approved is False
    assert verdict.fatal_error is True
    assert verdict.verification_status is VerificationStatus.VERIFICATION_UNAVAILABLE


@pytest.mark.asyncio
async def test_nonfatal_critic_concern_is_not_relabelled_as_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _IncompleteAnswerCritic:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return {
                "approved": False,
                "fatal_error": False,
                "reason_code": "incomplete_answer",
                "critique": "The answer could use more detail.",
            }

    monkeypatch.setattr(
        "vietnam_legal_agent.infra.llm_instances.get_llm_smart",
        lambda: _IncompleteAnswerCritic(),
    )
    verdict = await LegalCriticReviewer().review("q", "Theo Điều 25 [1].", [_document()])

    assert verdict.approved is False
    assert verdict.fatal_error is False
    assert verdict.verification_status is VerificationStatus.UNSUPPORTED_CLAIM
    assert verdict.reason_code == "incomplete_answer"


@pytest.mark.asyncio
async def test_critic_receives_versioned_lookup_scope_and_current_status_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CapturingModel:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []
            self.system_prompts: list[str] = []

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, messages):
            import json

            self.system_prompts.append(messages[0][1])
            self.payloads.append(json.loads(messages[1][1].partition("\n")[2]))
            return {"approved": True, "reason_code": "ok"}

    import vietnam_legal_agent.infra.llm_instances

    model = _CapturingModel()
    monkeypatch.setattr(vietnam_legal_agent.infra.llm_instances, "get_llm_smart", lambda: model)
    document = _document()
    document.metadata.update({
        "Document_Number": "45/2019/QH14",
        "source_title": "Bộ luật Lao động số 45/2019/QH14",
    })
    reviewer = LegalCriticReviewer()

    await reviewer.review(
        "Điều 25 Bộ luật Lao động số 45/2019/QH14 quy định gì?",
        "Theo Điều 25 [1]. Hiệu lực hiện hành chưa được xác minh.",
        [document],
        source_version_only=True,
    )
    await reviewer.review(
        "Điều 25 Bộ luật Lao động số 45/2019/QH14 hiện nay còn hiệu lực không?",
        "Chưa xác minh được hiệu lực hiện hành.",
        [document],
        source_version_only=False,
    )

    assert model.payloads[0]["source_version_only"] is True
    assert model.payloads[1]["source_version_only"] is False
    assert all("giới hạn bằng chứng" in prompt for prompt in model.system_prompts)
    assert all("phải được approved = True" in prompt for prompt in model.system_prompts)
    assert all("phạm vi của chủ thể, loại giao dịch" in prompt for prompt in model.system_prompts)


@pytest.mark.asyncio
async def test_guardrails_pass_source_version_scope_to_critic() -> None:
    document = _document()
    document.metadata.update({
        "Document_Number": "45/2019/QH14",
        "source_title": "Bộ luật Lao động số 45/2019/QH14",
    })
    critic = StaticLegalCriticReviewer()

    valid, reason, _answer, _citations = await AgentGuardrails.check_output(
        "Nội dung theo Điều 25 [1].",
        [document],
        query="Điều 25 Bộ luật Lao động số 45/2019/QH14 quy định gì?",
        require_evidence=True,
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        task_type="legal_lookup",
        critic_reviewer=critic,
    )

    assert valid is True
    assert reason == "ok"
    assert critic.source_version_only_calls == [True]


class _SequenceVerifier:
    def __init__(self) -> None:
        self.calls = 0

    async def verify(
        self,
        _answer: str,
        _documents: list[DocumentRecord],
        *,
        query: str = "",
    ) -> ClaimSupportResult:
        _ = query
        self.calls += 1
        return ClaimSupportResult(supported=self.calls == 1)


@pytest.mark.asyncio
async def test_corrected_answer_is_rechecked_without_repeating_critic() -> None:
    verifier = _SequenceVerifier()
    critic = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=True,
            corrected_answer="Bản hiệu chỉnh vẫn viện dẫn Điều 25 [1].",
        )
    )

    valid, reason, _fallback, _citations = await AgentGuardrails.check_output(
        "Bản nháp theo Điều 25 [1].",
        [_document()],
        query="Điều 25?",
        require_evidence=True,
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        claim_verifier=verifier,
        critic_reviewer=critic,
        enforce_legal_safety_circuit_breaker=True,
    )

    assert valid is False
    assert reason == "corrected_answer_unsupported_claim"
    assert verifier.calls == 2
