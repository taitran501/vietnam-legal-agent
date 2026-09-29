from __future__ import annotations

import pytest

from epr_agent.agent.guardrails import AgentGuardrails
from epr_agent.domain.legal import explicit_anchors, parse_required_anchors
from epr_agent.domain.models import DocumentRecord
from epr_agent.domain.routes import ROUTE_SPECS, RouteType
from epr_agent.domain.v4 import RetrievalRequest
from epr_agent.domain.verification import VerificationPolicy, VerificationStatus
from epr_agent.tools.verifier import (
    ClaimSupportResult,
    LegalCriticReviewer,
    LegalCriticVerdict,
    StaticLegalCriticReviewer,
    StructuredClaimSupportVerifier,
)


def _document() -> DocumentRecord:
    return DocumentRecord(
        content="Điều 77 quy định trách nhiệm tái chế và các điều kiện thực hiện. " * 8,
        document_id="law-77",
        source="legal",
        metadata={"legal_anchor": "Điều 77", "source": "Luật BVMT"},
    )


def test_route_matrix_owns_verification_policy() -> None:
    assert ROUTE_SPECS[RouteType.LEGAL_LOOKUP].verification_policy is VerificationPolicy.LEGAL_CORPUS
    assert ROUTE_SPECS[RouteType.CASE_ASSESSMENT].verification_policy is VerificationPolicy.LEGAL_CORPUS
    assert ROUTE_SPECS[RouteType.COMPLIANCE_CHECKLIST].verification_policy is VerificationPolicy.LEGAL_CORPUS
    assert ROUTE_SPECS[RouteType.RESEARCH_WEB].verification_policy is VerificationPolicy.WEB
    assert ROUTE_SPECS[RouteType.CHITCHAT].verification_policy is VerificationPolicy.NONE
    assert ROUTE_SPECS[RouteType.OUT_OF_SCOPE].verification_policy is VerificationPolicy.NONE


def test_required_anchor_parser_deduplicates_and_reports_invalid_values() -> None:
    parsed, invalid = parse_required_anchors(["Điều 77", "Điều 77", "not-an-anchor"])

    assert [anchor.key() for anchor in parsed] == ["Điều 77"]
    assert invalid == ["not-an-anchor"]


def test_required_anchor_parser_supports_appendix_addresses_and_preserves_document_scope() -> None:
    parsed, invalid = parse_required_anchors(["Nghị định 08/2022/NĐ-CP Phụ lục XXII"])

    assert invalid == []
    assert [anchor.key() for anchor in parsed] == ["08/2022/NĐ-CP | Phụ lục XXII"]
    combined = explicit_anchors("Điều 78 và Phụ lục XXII")
    assert [anchor.appendix for anchor in combined if anchor.appendix] == ["Phụ lục XXII"]


@pytest.mark.asyncio
async def test_retrieval_boundary_rejects_unparseable_required_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import epr_agent.config

    monkeypatch.setattr(
        epr_agent.config,
        "get_settings",
        lambda: type("SettingsDouble", (), {"enable_official_delta_retrieval": False})(),
    )
    from epr_agent.tools.retrieval import QdrantLegalRetrievalGateway, RequiredAnchorParseError

    with pytest.raises(RequiredAnchorParseError, match="required_anchor_parse_failed"):
        await QdrantLegalRetrievalGateway().legal(
            RetrievalRequest(route="case_assessment", query="EPR", required_anchors=["???"])
        )


@pytest.mark.asyncio
async def test_guardrail_missing_legal_dependencies_fails_closed() -> None:
    valid, reason, _fallback, _citations = await AgentGuardrails.check_output(
        "Theo Điều 77 [1].",
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

    import epr_agent.infra.llm_instances

    monkeypatch.setattr(epr_agent.infra.llm_instances, "get_llm_smart", lambda: _BrokenModel())
    result = await StructuredClaimSupportVerifier().verify("Theo Điều 77 [1].", [_document()])

    assert result.supported is False
    assert result.verification_status is VerificationStatus.VERIFICATION_UNAVAILABLE
    assert result.reason_code == "verifier_fallback"


@pytest.mark.asyncio
async def test_legacy_no_evidence_reason_is_not_promoted_to_supported() -> None:
    class _LegacyVerifier:
        async def verify(self, _answer: str, _documents: list[DocumentRecord]) -> ClaimSupportResult:
            return ClaimSupportResult(supported=False, reason_code="no_evidence_for_claims")

    valid, reason, _fallback, _citations = await AgentGuardrails.check_output(
        "Theo Điều 77 [1].",
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
        "epr_agent.infra.llm_instances.get_llm_smart",
        lambda: _LegacyCriticModel(),
    )
    verdict = await LegalCriticReviewer().review("q", "Theo Điều 77 [1].", [_document()])

    assert verdict.approved is False
    assert verdict.fatal_error is True
    assert verdict.verification_status is VerificationStatus.VERIFICATION_UNAVAILABLE


@pytest.mark.asyncio
async def test_critic_receives_versioned_lookup_scope_and_current_status_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CapturingModel:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, messages):
            import json

            self.payloads.append(json.loads(messages[1][1].partition("\n")[2]))
            return {"approved": True, "reason_code": "ok"}

    import epr_agent.infra.llm_instances

    model = _CapturingModel()
    monkeypatch.setattr(epr_agent.infra.llm_instances, "get_llm_smart", lambda: model)
    document = _document()
    document.metadata.update({
        "Document_Number": "08/2022/NĐ-CP",
        "source_title": "Nghị định số 08/2022/NĐ-CP",
    })
    reviewer = LegalCriticReviewer()

    await reviewer.review(
        "Điều 77 Nghị định 08/2022/NĐ-CP quy định gì?",
        "Theo Điều 77 [1]. Hiệu lực hiện hành chưa được xác minh.",
        [document],
        source_version_only=True,
    )
    await reviewer.review(
        "Điều 77 Nghị định 08/2022/NĐ-CP hiện nay còn hiệu lực không?",
        "Chưa xác minh được hiệu lực hiện hành.",
        [document],
        source_version_only=False,
    )

    assert model.payloads[0]["source_version_only"] is True
    assert model.payloads[1]["source_version_only"] is False


@pytest.mark.asyncio
async def test_guardrails_pass_source_version_scope_to_critic() -> None:
    document = _document()
    document.metadata.update({
        "Document_Number": "08/2022/NĐ-CP",
        "source_title": "Nghị định số 08/2022/NĐ-CP",
    })
    critic = StaticLegalCriticReviewer()

    valid, reason, _answer, _citations = await AgentGuardrails.check_output(
        "Nội dung theo Điều 77 [1].",
        [document],
        query="Điều 77 Nghị định 08/2022/NĐ-CP quy định gì?",
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

    async def verify(self, _answer: str, _documents: list[DocumentRecord]) -> ClaimSupportResult:
        self.calls += 1
        return ClaimSupportResult(supported=self.calls == 1)


@pytest.mark.asyncio
async def test_corrected_answer_is_rechecked_without_repeating_critic() -> None:
    verifier = _SequenceVerifier()
    critic = StaticLegalCriticReviewer(
        verdict=LegalCriticVerdict(
            approved=True,
            corrected_answer="Bản hiệu chỉnh vẫn viện dẫn Điều 77 [1].",
        )
    )

    valid, reason, _fallback, _citations = await AgentGuardrails.check_output(
        "Bản nháp theo Điều 77 [1].",
        [_document()],
        query="Điều 77?",
        require_evidence=True,
        verification_policy=VerificationPolicy.LEGAL_CORPUS,
        claim_verifier=verifier,
        critic_reviewer=critic,
        enforce_legal_safety_circuit_breaker=True,
    )

    assert valid is False
    assert reason == "corrected_answer_unsupported_claim"
    assert verifier.calls == 2
