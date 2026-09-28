"""Tool registry for the autonomous Vietnamese legal agent.

Defines the 9 tools available for the LLM to call during its cognitive loop.
Each tool wraps existing domain gateways and rule engines, returning structured
observations with error isolation and follow-up guidance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from epr_agent.domain.epr_rules import (
    CaseFormResolver,
    follow_up_question,
)
from epr_agent.domain.legal import parse_required_anchors
from epr_agent.domain.models import DocumentRecord, EvidenceAssessment, TaskType
from epr_agent.domain.v4 import RetrievalRequest
from epr_agent.tools.cache import RedisExactAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator, verify_citations
from epr_agent.tools.generation import EvidenceGenerationGateway, GenerationGateway
from epr_agent.tools.history import HistoryGateway, UnifiedHistoryGateway
from epr_agent.tools.legal_readiness import LegalReadinessProvider
from epr_agent.tools.retrieval import QdrantLegalRetrievalGateway, RequiredAnchorParseError, RetrievalGateway

logger = logging.getLogger(__name__)


@dataclass
class ToolDependencies:
    """Injectable dependencies for tool execution."""

    retrieval: RetrievalGateway
    evidence_evaluator: EvidenceEvaluator
    generation: GenerationGateway
    cache: ScopedAnswerCache
    history: HistoryGateway
    case_resolver: CaseFormResolver
    legal_readiness: LegalReadinessProvider | None = None


_default_deps: ToolDependencies | None = None


def get_tool_dependencies() -> ToolDependencies:
    """Lazy initialization of production tool adapters."""
    global _default_deps
    if _default_deps is None:
        from scripts.canonical_corpus import corpus_sha256

        from epr_agent.config import get_settings
        from epr_agent.tools.legal_readiness import LegalReadinessGate, sha256_file

        settings = get_settings()
        appendix_path = (
            settings.appendix_xxii_data_path
            if getattr(settings, "agent_pipeline_version", "pipeline-v3") == "pipeline-v4"
            else None
        )
        corpus_sha = corpus_sha256(
            law_path=settings.law_data_path,
            manifest_path=settings.corpus_manifest_path,
            appendix_path=appendix_path,
        )
        legal_readiness = (
            LegalReadinessGate(
                settings.legal_readiness_manifest_path,
                corpus_sha256=corpus_sha,
                amendment_map_sha256=sha256_file(settings.amendment_map_path),
                rule_pack_sha256=sha256_file(settings.rule_pack_path),
            )
            if settings.enforce_legal_readiness_gate
            else None
        )

        _default_deps = ToolDependencies(
            retrieval=QdrantLegalRetrievalGateway(),
            evidence_evaluator=EvidenceEvaluator(
                min_docs=getattr(settings, "min_legal_evidence_docs", 1),
                min_chars=getattr(settings, "min_legal_evidence_chars", 160),
            ),
            generation=EvidenceGenerationGateway(),
            cache=ScopedAnswerCache(
                RedisExactAnswerCache(),
                corpus_version=str(getattr(settings, "corpus_version", "epr-corpus-v1")),
                corpus_id=str(getattr(settings, "corpus_id", "epr")),
                corpus_sha=corpus_sha,
                embedding_profile=str(getattr(settings, "embedding_profile", "openai-text-embedding-3-small-v1")),
                legal_readiness_sha=legal_readiness.manifest_sha256 if legal_readiness else "",
            ),
            history=UnifiedHistoryGateway(),
            case_resolver=CaseFormResolver(),
            legal_readiness=legal_readiness,
        )
    return _default_deps


def set_tool_dependencies(deps: ToolDependencies | None) -> None:
    """Override dependencies (used in unit/integration tests)."""
    global _default_deps
    _default_deps = deps


def _suggest_followup(query: str, assessment: EvidenceAssessment) -> str | None:
    """Suggest query revision to help the agent recover from insufficient evidence."""
    if assessment.reason == "explicit_article_not_found":
        return f"Thử bỏ số Điều cụ thể và tìm kiếm theo nội dung / từ khóa: '{query}'"
    if assessment.reason == "content_too_short":
        return f"Thử mở rộng từ khóa hoặc thêm tên văn bản (ví dụ: '{query} Nghị định 08')"
    if assessment.reason == "not_enough_docs":
        return "Thử tìm bằng thuật ngữ pháp lý cụ thể hơn hoặc tên đối tượng liên quan."
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 9 AGENT TOOL FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════


async def search_legal_provisions(
    query: str,
    required_anchors: list[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Tìm kiếm các điều khoản pháp luật trong kho văn bản pháp luật chính thức (Qdrant).

    Sử dụng khi: Cần tra cứu quy định, điều khoản, ngưỡng, nghĩa vụ, hoặc chế tài pháp lý.
    Không sử dụng khi: Câu hỏi xã giao (chitchat) hoặc đã có đầy đủ bằng chứng cần thiết.

    Args:
        query: Câu truy vấn pháp lý tiếng Việt cụ thể (ví dụ: 'ngưỡng doanh thu tái chế bao bì nhựa Điều 54').
        required_anchors: Danh sách Điều/Khoản cần đối chiếu bắt buộc nếu đã biết (ví dụ: ['Điều 77']).
        top_k: Số lượng văn bản trả về (1-8, mặc định 5).
    """
    deps = get_tool_dependencies()
    raw_required_anchors = list(required_anchors or [])
    request = RetrievalRequest(
        route="legal_lookup",
        issue_id="agent_legal_lookup",
        query=query,
        required_anchors=raw_required_anchors,
        top_k=max(1, min(top_k, 20)),
    )
    try:
        parsed_anchors, invalid_anchors = parse_required_anchors(raw_required_anchors)
        if invalid_anchors:
            extra_terms = " ".join(a for a in invalid_anchors if a.lower() not in query.lower())
            if extra_terms:
                query = f"{query} {extra_terms}".strip()
                request.query = query
        request.required_anchors = [a.article or a.key() for a in parsed_anchors]
        docs = await deps.retrieval.legal(request)
        selected = docs[: max(1, min(top_k, 8))]
        assessment = deps.evidence_evaluator.evaluate(
            query,
            selected,
            TaskType.LEGAL_LOOKUP,
            expected_articles={anchor.article for anchor in parsed_anchors if anchor.article} or None,
            expected_anchors=parsed_anchors or None,
        )
        return {
            "documents": [d.to_dict() for d in selected],
            "total_found": len(docs),
            "required_anchors": raw_required_anchors,
            "evidence_sufficient": assessment.sufficient,
            "reason": assessment.reason,
            "suggested_followup_query": (
                _suggest_followup(query, assessment) if not assessment.sufficient else None
            ),
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001 - tools must return safe observations
        logger.warning("search_legal_provisions failed for query=%r: %s", query, exc)
        reason = (
            "required_anchor_parse_failed"
            if isinstance(exc, RequiredAnchorParseError)
            else f"retrieval_error: {type(exc).__name__}"
        )
        return {
            "documents": [],
            "total_found": 0,
            "evidence_sufficient": False,
            "required_anchors": raw_required_anchors,
            "reason": reason,
            "error": str(exc),
            "ok": False,
        }


async def search_web_official(query: str) -> dict[str, Any]:
    """Tìm kiếm thông tin trên các cổng thông tin pháp luật chính thức (vbpl.vn, vanban.chinhphu.vn, thuvienphapluat.vn).

    Sử dụng khi: Người dùng yêu cầu tra cứu nguồn web công khai hoặc khi kho văn bản nội bộ chưa cập nhật.
    Lưu ý: Chỉ tìm kiếm trên các tên miền cơ quan nhà nước và cổng pháp lý được cấp phép.

    Args:
        query: Câu truy vấn tìm kiếm tiếng Việt.
    """
    deps = get_tool_dependencies()
    try:
        answer, docs = await deps.generation.web(query)
        assessment = deps.evidence_evaluator.evaluate(query, docs, TaskType.LEGAL_LOOKUP)
        return {
            "answer_summary": answer,
            "documents": [d.to_dict() for d in docs],
            "total_found": len(docs),
            "evidence_sufficient": assessment.sufficient,
            "reason": assessment.reason,
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_web_official failed for query=%r: %s", query, exc)
        return {
            "answer_summary": "",
            "documents": [],
            "total_found": 0,
            "evidence_sufficient": False,
            "reason": f"web_search_error: {type(exc).__name__}",
            "error": str(exc),
            "ok": False,
        }


async def lookup_answer_cache(query: str, route: str = "legal_lookup") -> dict[str, Any]:
    """Tra cứu bộ nhớ đệm (Redis Cache) xem câu hỏi pháp lý tương tự đã có câu trả lời được kiểm chứng chưa.

    Sử dụng khi: Bắt đầu xử lý câu hỏi tra cứu pháp luật (legal_lookup hoặc legal_explain_compare).
    Không dùng khi: Đánh giá case cụ thể (case_assessment) do phụ thuộc vào tình huống người dùng.

    Args:
        query: Câu hỏi cần tra cứu cache.
        route: Phân loại câu hỏi ('legal_lookup' hoặc 'legal_explain_compare').
    """
    deps = get_tool_dependencies()
    try:
        readiness = None
        readiness_provider = deps.legal_readiness
        if readiness_provider is not None:
            readiness = readiness_provider.audit()
            deps.cache.update_legal_readiness_sha(readiness.manifest_sha256)
            if not readiness.legally_ready:
                readiness_reason = (
                    "legal_readiness_invalid"
                    if readiness.status.value == "invalid"
                    else readiness.reason
                )
                return {
                    "hit": False,
                    "answer": None,
                    "cache_key": deps.cache.build_key(TaskType.LEGAL_LOOKUP, query, route=route),
                    "reason": readiness_reason,
                    "legal_readiness_status": readiness.status.value,
                    "legal_readiness_issues": list(readiness.issues),
                    "ok": True,
                }
        cached, key = await deps.cache.lookup(TaskType.LEGAL_LOOKUP, query, route=route)
        if cached is not None:
            docs = [DocumentRecord.from_dict(d) for d in cached.evidence]
            if readiness_provider is not None and readiness is not None:
                allowed, readiness_reason = readiness_provider.allows_documents(docs)
                if not allowed:
                    return {
                        "hit": False,
                        "answer": None,
                        "cache_key": key,
                        "reason": readiness_reason,
                        "legal_readiness_status": readiness.status.value,
                        "ok": True,
                    }
            valid, _, _reason = verify_citations(cached.answer, docs, TaskType.LEGAL_LOOKUP)
            if valid:
                return {
                    "hit": True,
                    "answer": cached.answer,
                    "evidence": list(cached.evidence),
                    "citations": list(cached.citations),
                    "source": cached.source,
                    "cache_key": key,
                    "ok": True,
                }
        return {"hit": False, "answer": None, "cache_key": key, "ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.debug("lookup_answer_cache failed: %s", exc)
        return {"hit": False, "answer": None, "error": str(exc), "ok": False}


async def evaluate_legal_case(
    legal_domain: str,
    facts: dict[str, str],
) -> dict[str, Any]:
    """Đánh giá tình huống pháp lý và xác định trách nhiệm/rủi ro trên các lĩnh vực pháp luật Việt Nam.

    Lĩnh vực hỗ trợ (legal_domain):
    - 'labor': Đơn phương chấm dứt HĐLĐ (Đ.36/41 BLLĐ), tiền lương làm thêm giờ, trợ cấp thôi việc.
    - 'civil_contract': Tăng giá thuê nhà (Đ.478 BLDS), phạt vi phạm hợp đồng, đặt cọc, lãi suất vay.
    - 'marriage_family': Ly hôn đơn phương (Đ.56 Luật HN&GĐ), xin cấp trích lục kết hôn bị giữ.
    - 'corporate': Quyền cổ đông 5% triệu tập họp ĐHĐCĐ bất thường (Đ.115 Luật Doanh nghiệp).
    - 'land': Bồi thường thu hồi đất nông nghiệp (Đ.96 Luật Đất đai), điều kiện cấp sổ đỏ.
    - 'traffic': Mức phạt vượt đèn đỏ, nồng độ cồn theo Nghị định 100/2019/NĐ-CP & NĐ 123/2021/NĐ-CP.
    - 'tax': Thuế thu nhập cá nhân, thuế doanh nghiệp, giảm trừ gia cảnh theo Luật Quản lý thuế.
    - 'intellectual_property': Đăng ký nhãn hiệu, bảo hộ quyền tác giả theo Luật SHTT.
    - 'environmental': Trách nhiệm bảo vệ môi trường, tái chế theo Luật BVMT 2020.
    - 'general': Đánh giá tình huống pháp lý tổng quát khác.

    Args:
        legal_domain: Tên lĩnh vực pháp luật cần đánh giá.
        facts: Từ điển các sự kiện/dữ kiện thu thập từ người dùng.
    """
    from epr_agent.domain.legal_rules import evaluate_universal_case

    try:
        res = evaluate_universal_case(legal_domain=legal_domain, facts=facts)
        if isinstance(res, dict) and res.get("ok"):
            provisions = res.get("applicable_provisions") or []
            conclusion = str(res.get("conclusion") or "")
            reasons = res.get("reasons") or []
            text_summary = f"{conclusion} {' '.join(str(r) for r in reasons)}".strip()
            docs = []
            for i, prov in enumerate(provisions):
                docs.append({
                    "id": f"eval_prov_{i+1}",
                    "document_id": f"eval_prov_{i+1}",
                    "text": f"{prov}. {text_summary}",
                    "content": f"{prov}. {text_summary}",
                    "source": "legal",
                    "title": str(prov),
                    "source_title": str(prov),
                    "metadata": {"Source_Title": str(prov)},
                })
            if docs:
                res["evidence"] = docs
                res["documents"] = docs
        return res
    except Exception as exc:  # noqa: BLE001
        logger.warning("evaluate_legal_case failed for domain=%r: %s", legal_domain, exc)
        return {"status": "error", "error": str(exc), "ok": False}


async def calculate_statutory_amounts(
    calculation_type: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Thực hiện các phép tính toán số liệu pháp lý chuẩn hóa theo luật định Việt Nam.

    Các loại tính toán hỗ trợ (calculation_type):
    - 'overtime_salary': Tính tiền lương làm thêm giờ (150% ngày thường, 200% chủ nhật, 300% ngày lễ/tết theo Đ.98 BLLĐ).
      Params: {'monthly_salary_vnd': float, 'hourly_wage_vnd': float, 'overtime_hours': float, 'day_type': 'weekday'|'weekend'|'holiday', 'is_night': bool}
    - 'unlawful_termination_compensation': Bồi thường sa thải trái luật theo Đ.41 BLLĐ (ít nhất 2 tháng lương + lương ngày không làm việc + bồi thường vi phạm báo trước).
      Params: {'monthly_salary_vnd': float, 'months_unworked': float, 'unnotified_days': float}
    - 'severance_allowance': Trợ cấp thôi việc theo Đ.46 BLLĐ (0.5 tháng lương/năm làm việc).
      Params: {'monthly_salary_average_6m_vnd': float, 'qualifying_working_years': float}
    - 'probation_wage_floor': Mức sàn tiền lương thử việc tối thiểu 85% theo Đ.26 BLLĐ.
      Params: {'official_salary_vnd': float, 'actual_probation_wage_vnd': float}
    - 'traffic_fine': Tra cứu khung phạt vi phạm giao thông theo NĐ 100/2019 & NĐ 123/2021 (cồn, đèn đỏ, đèn vàng).
      Params: {'vehicle_type': 'motorbike'|'car', 'violation_act': 'alcohol'|'traffic_light', 'alcohol_concentration': 'level_1'|'level_2'|'level_3'}
    - 'traffic_accident_damage_compensation': Tính tổng tiền bồi thường thiệt hại do tai nạn giao thông/xâm phạm sức khỏe & tài sản theo Điều 584, 585, 589, 590 Bộ luật Dân sự 2015.
      Params: {'medical_expenses_vnd': float, 'property_damage_vnd': float, 'lost_income_vnd': float, 'monthly_income_vnd': float, 'months_unworked': float, 'caretaker_costs_vnd': float}
    - 'household_business_tax': Tính thuế khoán hộ kinh doanh cá thể (GTGT + TNCN theo Thông tư 40/2021/TT-BTC).
      Params: {'monthly_revenue_vnd': float, 'business_sector': 'food_and_beverage'|'retail_trade'|'other_services'}
    - 'personal_income_tax': Tính thuế TNCN biểu lũy tiến 7 bậc theo Luật Thuế TNCN (giảm trừ bản thân 11tr, người phụ thuộc 4.4tr).
      Params: {'monthly_income_vnd': float, 'dependents_count': int, 'insurance_deduction_vnd': float}
    - 'late_payment_interest': Tính tiền lãi chậm trả và trần lãi suất vay 20%/năm theo Điều 468 BLDS 2015.
      Params: {'principal_vnd': float, 'overdue_days': int, 'agreed_rate_annual_percent': float}

    Args:
        calculation_type: Loại công thức cần tính toán.
        parameters: Các tham số đầu vào cho công thức.
    """
    from epr_agent.domain.legal_rules import calculate_legal_formula

    try:
        res = calculate_legal_formula(calculation_type=calculation_type, parameters=parameters)
        if isinstance(res, dict) and res.get("ok"):
            legal_basis = str(res.get("legal_basis") or "")
            summary = str(res.get("formatted_summary") or res.get("formula") or "")
            if legal_basis:
                doc = {
                    "id": "calc_basis_1",
                    "document_id": "calc_basis_1",
                    "text": f"{legal_basis}: {summary}",
                    "content": f"{legal_basis}: {summary}",
                    "source": "legal",
                    "title": legal_basis,
                    "source_title": legal_basis,
                    "metadata": {"Source_Title": legal_basis},
                }
                res["evidence"] = [doc]
                res["documents"] = [doc]
        return res
    except Exception as exc:  # noqa: BLE001
        logger.warning("calculate_statutory_amounts failed for type=%r: %s", calculation_type, exc)
        return {"status": "error", "error": str(exc), "ok": False}


async def get_case_form_fields(
    task_type: str = "assess_legal_case",
    legal_domain: str = "general",
    known_facts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Lấy danh sách các trường thông tin cần thiết và xác định thông tin nào còn thiếu theo từng lĩnh vực luật.

    Args:
        task_type: Loại tác vụ ('assess_legal_case', 'build_compliance_checklist', hoặc 'assess_epr_obligation').
        legal_domain: Lĩnh vực pháp luật ('labor', 'civil_contract', 'marriage_family', 'corporate', 'land', 'traffic', 'tax', 'environmental', 'general').
        known_facts: Các thông tin người dùng đã cung cấp sẵn.
    """
    from epr_agent.domain.legal_rules import UniversalCaseFormResolver

    try:
        deps = get_tool_dependencies()
        if isinstance(legal_domain, dict) and known_facts is None:
            known_facts = legal_domain
            legal_domain = "general"
        if task_type in ("assess_epr_obligation", "build_compliance_checklist") and (not legal_domain or legal_domain == "general"):
            legal_domain = "epr"

        # If explicitly requesting EPR legacy task form
        if legal_domain in ("epr", "bao_bi"):
            form_state = deps.case_resolver.from_strings(
                task_type=task_type,
                facts=None,
                updates=known_facts or {},
            )
            return {
                "domain": "epr",
                "status": form_state.status,
                "missing_facts": list(form_state.missing_facts),
                "completed_count": form_state.completed_count,
                "required_count": form_state.required_count,
                "fields": [f.model_dump(mode="json") for f in form_state.fields],
                "submission_blocked_reason": form_state.submission_blocked_reason,
                "suggested_follow_up": follow_up_question(list(form_state.missing_facts)),
                "allow_skip": True,
                "ok": True,
            }

        # Multi-domain dynamic form resolver
        resolver = UniversalCaseFormResolver()
        return resolver.resolve_form_state(
            legal_domain=legal_domain,
            known_facts=known_facts or {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_case_form_fields failed: %s", exc)
        return {"status": "error", "missing_facts": [], "fields": [], "error": str(exc), "ok": False}


async def load_conversation_context(user_id: str, conversation_id: str) -> dict[str, Any]:
    """Tải lịch sử hội thoại và tình huống vụ việc đang xử lý dở dang (nếu có).

    Args:
        user_id: Mã định danh người dùng.
        conversation_id: Mã phiên hội thoại.
    """
    deps = get_tool_dependencies()
    try:
        snapshot = await deps.history.load(user_id, conversation_id, max_messages=6)
        return {
            "history_messages": snapshot.history,
            "history_summary": snapshot.summary,
            "active_case": snapshot.active_case,
            "has_active_case": bool(snapshot.active_case),
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_conversation_context failed: %s", exc)
        return {"history_messages": [], "history_summary": "", "active_case": None, "error": str(exc), "ok": False}


async def ask_user_for_clarification(
    question: str,
    missing_fields: list[str] | None = None,
    legal_domain: str = "general",
    suggested_options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tạo câu hỏi yêu cầu người dùng bổ sung thông tin còn thiếu kèm panel lựa chọn (Open-Design Pattern).

    Sử dụng khi: Cần người dùng làm rõ hoặc cung cấp thêm dữ kiện để tiếp tục đánh giá.
    LƯU Ý: Hỗ trợ nút 'Bỏ qua' (allow_skip=True) cho phép người dùng lướt qua nếu muốn tư vấn tổng quát.

    Args:
        question: Câu hỏi hướng dẫn người dùng bổ sung thông tin bằng tiếng Việt.
        missing_fields: Danh sách các trường thông tin cần làm rõ (ví dụ: ['contract_type', 'monthly_salary_vnd']).
        legal_domain: Lĩnh vực pháp luật liên quan (labor, civil_contract, land, traffic, tax, etc.).
        suggested_options: Danh sách các option gợi ý chọn nhanh cho người dùng.
    """
    form_payload = {
        "id": f"clarify_{legal_domain}",
        "title": "Làm rõ thông tin tình huống",
        "domain": legal_domain,
        "question_text": question,
        "missing_fields": missing_fields or [],
        "suggested_options": suggested_options or [],
        "allow_skip": True,
        "submit_label": "Tiếp tục",
        "skip_label": "Bỏ qua",
    }
    return {
        "action": "ask_user",
        "status": "need_clarification",
        "question": question,
        "missing_fields": missing_fields or [],
        "question_form": form_payload,
        "allow_skip": True,
        "skip_label": "Bỏ qua",
        "awaiting_user_input": True,
        "ok": True,
    }



ALL_AGENT_TOOLS = [
    search_legal_provisions,
    search_web_official,
    lookup_answer_cache,
    evaluate_legal_case,
    get_case_form_fields,
    calculate_statutory_amounts,
    load_conversation_context,
    ask_user_for_clarification,
]
