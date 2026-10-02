"""LangGraph implementation of the bounded legal workflow."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.agent.understanding import StructuredTaskUnderstandingGateway, TaskUnderstandingGateway
from vietnam_legal_agent.domain.corpus import CorpusDescriptor, vietnamese_law_corpus
from vietnam_legal_agent.domain.legal import EMBEDDING_PROFILE, explicit_anchors
from vietnam_legal_agent.domain.models import (
    AgentState,
)
from vietnam_legal_agent.domain.tasks import (
    preserve_explicit_anchors,
)
from vietnam_legal_agent.domain.verification import (
    VerificationStatus,
)
from vietnam_legal_agent.tools.cache import RedisExactAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import (
    EvidenceEvaluator,
    legal_relevance_checker,
)
from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway, GenerationGateway
from vietnam_legal_agent.tools.history import HistoryGateway, UnifiedHistoryGateway
from vietnam_legal_agent.tools.legal_readiness import (
    LegalReadinessProvider,
)
from vietnam_legal_agent.tools.retrieval import (
    RetrievalGateway,
    UniversalLegalRetrievalGateway,
)
from vietnam_legal_agent.tools.verifier import (
    ClaimSupportResult,
    ClaimSupportVerifier,
    LegalCriticReviewer,
    StructuredClaimSupportVerifier,
    claim_segments_for_verification,
)

logger = logging.getLogger(__name__)

_SOURCE_VERSION_CAVEAT = (
    "Lưu ý: Câu trả lời tóm tắt nội dung trong nguồn được trích dẫn; dữ liệu hiện "
    "chưa xác nhận các cập nhật hoặc hiệu lực hiện hành."
)


def _append_source_version_caveat(answer: str) -> str:
    cleaned = answer.rstrip()
    if not cleaned or _has_source_version_caveat(cleaned):
        return cleaned
    return f"{cleaned}\n\n{_SOURCE_VERSION_CAVEAT}"


def _has_source_version_caveat(answer: str) -> bool:
    text = " ".join((answer or "").casefold().split())
    if _SOURCE_VERSION_CAVEAT.casefold() in text:
        return True
    return bool(
        re.search(
            r"(?:chưa|không)\s+(?:thể\s+)?(?:xác nhận|kiểm chứng|đối chiếu|xác minh).{0,100}"
            r"(?:hiệu lực|quy định|nội dung).{0,45}(?:hiện hành|mới nhất|sửa đổi|cập nhật)"
            r"|(?:hiệu lực|quy định).{0,35}(?:hiện hành|mới nhất).{0,60}"
            r"(?:chưa|không)\s+(?:được\s+)?(?:xác nhận|kiểm chứng|đối chiếu|xác minh)",
            text,
        )
    )


def _claim_verifier_feedback(
    answer: str,
    support: ClaimSupportResult,
    status: VerificationStatus,
) -> dict[str, Any]:
    claims = claim_segments_for_verification(answer)
    return {
        "status": status.value,
        "reason": str(support.reason_code or "")[:1000],
        "unsupported_claims": [
            {"claim_index": index, "text": claims[index - 1]}
            for index in support.unsupported_claim_indices
            if 1 <= index <= len(claims)
        ],
        "unsupported_claim_count": support.unsupported_claim_count,
    }


def _retrieval_document_key(document) -> str:
    metadata = document.metadata or {}
    for key in ("_id", "point_id", "chunk_id", "chunkId"):
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return f"{document.source}:{key}:{value}"
    digest = hashlib.sha256((document.content or "").encode("utf-8")).hexdigest()[:20]
    return f"{document.source}:{document.document_id}:{digest}"


def _merge_multi_query_results(
    results: list[list[Any]],
    *,
    query_indices: list[int] | None = None,
) -> list[Any]:
    """Fuse ranked candidate lists while retaining chunk-level identity."""

    reciprocal_rank_constant = 60
    ranked: dict[str, dict[str, Any]] = {}
    for result_index, documents in enumerate(results):
        query_index = query_indices[result_index] if query_indices is not None else result_index
        # Rewrites are independent retrieval views of the same user question.
        # Give them equal weight: a fixed preference for the first rewrite can
        # hide the directly relevant provision found by a later formulation.
        query_weight = 1.0
        for rank, document in enumerate(documents):
            key = _retrieval_document_key(document)
            entry = ranked.get(key)
            if entry is None:
                copied = type(document).from_dict(document.to_dict())
                entry = {"document": copied, "score": 0.0, "ranks": []}
                ranked[key] = entry
            else:
                copied = entry["document"]
                for score_key in (
                    "semantic_score",
                    "lexical_score",
                    "combined_score",
                    "rrf_score",
                    "rerank_score",
                ):
                    incoming_value = (document.metadata or {}).get(score_key)
                    if incoming_value is None:
                        continue
                    try:
                        incoming = float(incoming_value)
                    except (TypeError, ValueError):
                        continue
                    existing_value = (copied.metadata or {}).get(score_key)
                    if existing_value is None:
                        existing = None
                    else:
                        try:
                            existing = float(existing_value)
                        except (TypeError, ValueError):
                            existing = None
                    if existing is None or incoming > existing:
                        copied.metadata[score_key] = incoming
                if document.score is not None and (copied.score is None or document.score > copied.score):
                    copied.score = document.score
            entry["score"] += query_weight / (reciprocal_rank_constant + rank + 1)
            entry["ranks"].append({"query_index": query_index, "rank": rank + 1})

    ordered = sorted(ranked.values(), key=lambda item: item["score"], reverse=True)
    documents = []
    for entry in ordered:
        document = entry["document"]
        document.metadata["multi_query_rrf_score"] = entry["score"]
        document.metadata["multi_query_ranks"] = entry["ranks"]
        documents.append(document)
    return documents


def _build_retrieval_queries(
    original_query: str,
    standalone_query: str,
    proposed_queries: list[str] | None,
) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    allowed_anchors = {
        (field, value.casefold())
        for anchor in [*explicit_anchors(original_query), *explicit_anchors(standalone_query)]
        for field, value in (
            ("document_number", anchor.document_number),
            ("document_title", anchor.document_title),
            ("article", anchor.article),
            ("clause", anchor.clause),
            ("point", anchor.point),
            ("appendix", anchor.appendix),
        )
        if value
    }
    # Keep the user's wording as the baseline, then reserve the remaining
    # bounded slots for the focused legal rewrites. A standalone normalization
    # is only a fallback when it adds signal beyond those targeted queries.
    for candidate in [original_query, *(proposed_queries or []), standalone_query]:
        normalized = " ".join(str(candidate or "").split())
        if not normalized:
            continue
        normalized = preserve_explicit_anchors(original_query, normalized)
        candidate_anchors = {
            (field, value.casefold())
            for anchor in explicit_anchors(normalized)
            for field, value in (
                ("document_number", anchor.document_number),
                ("document_title", anchor.document_title),
                ("article", anchor.article),
                ("clause", anchor.clause),
                ("point", anchor.point),
                ("appendix", anchor.appendix),
            )
            if value
        }
        if candidate_anchors - allowed_anchors:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(normalized[:3000])
        if len(queries) == 3:
            break
    return queries


def _verification_status_for_reason(reason: str, *, valid: bool) -> VerificationStatus:
    if valid:
        return VerificationStatus.VERIFIED
    if reason in {
        "required_anchor_parse_failed",
        "legal_readiness_invalid",
        "verification_unavailable",
        "claim_support_verification_unavailable",
        "claim_support_verifier_unavailable",
    }:
        return VerificationStatus.VERIFICATION_UNAVAILABLE
    if reason in {"no_evidence_for_claims", "insufficient_evidence"}:
        return VerificationStatus.INSUFFICIENT_EVIDENCE
    if reason.startswith("claim_support_") and "insufficient_evidence" in reason:
        return VerificationStatus.INSUFFICIENT_EVIDENCE
    if (
        reason.startswith("claim_support_")
        or reason
        in {
            "article_reference_not_in_evidence",
            "citation_out_of_range",
            "legal_claim_without_citation",
        }
        or "unsupported_claim" in reason
        or reason == "critic_legal_flaw_rejected"
    ):
        return VerificationStatus.UNSUPPORTED_CLAIM
    if reason.startswith("corrected_answer_") and "unavailable" in reason:
        return VerificationStatus.VERIFICATION_UNAVAILABLE
    return VerificationStatus.INSUFFICIENT_EVIDENCE


@dataclass(slots=True)
class WorkflowDependencies:
    history: HistoryGateway
    cache: ScopedAnswerCache
    retrieval: RetrievalGateway
    evidence: EvidenceEvaluator
    generation: GenerationGateway
    planner: BoundedPlanner
    max_history_messages: int = 6
    understanding: TaskUnderstandingGateway | None = None
    corpus: CorpusDescriptor | None = None
    claim_verifier: ClaimSupportVerifier | None = None
    critic_reviewer: LegalCriticReviewer | None = None
    legal_readiness: LegalReadinessProvider | None = None
    enforce_legal_safety_circuit_breaker: bool = False


def default_dependencies() -> WorkflowDependencies:
    """Build production adapters lazily; importing the package needs no secrets."""

    from vietnam_legal_agent.config import get_settings

    settings = get_settings()
    manifest_path = settings.universal_corpus_manifest_path
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        corpus_sha = hashlib.sha256(manifest_bytes).hexdigest()
    except (OSError, json.JSONDecodeError):
        manifest = {}
        corpus_sha = ""
    cache_corpus_id = str(manifest.get("corpus_id") or "vietnamese_law")
    cache_corpus_version = str(getattr(settings, "corpus_version", "vietnamese-law-v1"))
    cache_corpus_version = str(manifest.get("corpus_version") or cache_corpus_version)
    legal_readiness = None
    return WorkflowDependencies(
        history=UnifiedHistoryGateway(),
        cache=ScopedAnswerCache(
            RedisExactAnswerCache(),
            corpus_version=cache_corpus_version,
            corpus_id=cache_corpus_id,
            corpus_sha=corpus_sha,
            embedding_profile=str(getattr(settings, "embedding_profile", EMBEDDING_PROFILE)),
            legal_readiness_sha=legal_readiness.manifest_sha256 if legal_readiness else "",
        ),
        retrieval=UniversalLegalRetrievalGateway(),
        evidence=EvidenceEvaluator(
            min_docs=getattr(settings, "min_legal_evidence_docs", 1),
            min_chars=getattr(settings, "min_legal_evidence_chars", 160),
            relevance_checker=(
                legal_relevance_checker(min_rerank_score=getattr(settings, "min_legal_rerank_score", 0.40))
                if getattr(settings, "enable_relevance_gate", True)
                else None
            ),
        ),
        generation=EvidenceGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=2, max_repairs=1, max_iterations=12),
        max_history_messages=max(2, int(getattr(settings, "history_context_messages", 6))),
        understanding=StructuredTaskUnderstandingGateway(),
        claim_verifier=StructuredClaimSupportVerifier(),
        critic_reviewer=LegalCriticReviewer(),
        legal_readiness=legal_readiness,
        enforce_legal_safety_circuit_breaker=settings.enforce_legal_safety_circuit_breaker,
        corpus=vietnamese_law_corpus(
            collection_alias=str(getattr(settings, "law_collection", "law_collection")),
            corpus_version=cache_corpus_version,
            corpus_sha=corpus_sha,
            embedding_profile=str(getattr(settings, "embedding_profile", EMBEDDING_PROFILE)),
        ),
    )


def _trace(state: AgentState, *, reason_code: str = "", payload: dict | None = None) -> None:
    """Attach operational facts to the latest node without logging raw prompts."""

    events = state.setdefault("trace_events", [])
    if not events:
        return
    event = events[-1]
    event["reason_code"] = reason_code
    if payload:
        event["payload"] = payload


def _tool_result(
    state: AgentState,
    tool: str,
    started_at: float,
    *,
    ok: bool,
    count: int = 0,
    error: str = "",
    metadata: dict | None = None,
) -> None:
    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
    state.setdefault("tool_results", []).append(
        {
            "tool": tool,
            "ok": ok,
            "latency_ms": latency_ms,
            "count": count,
            "error": error,
            "metadata": metadata or {},
        }
    )
    _trace(
        state,
        reason_code="tool_ok" if ok else "tool_failed",
        payload={"tool": tool, "latency_ms": latency_ms, "count": count, "error_code": error, **(metadata or {})},
    )
    logger.info(
        "%s",
        json.dumps(
            {
                "event": "agent_tool",
                "trace_id": state.get("trace_id"),
                "tool": tool,
                "ok": ok,
                "duration_ms": latency_ms,
                "count": count,
                "error_code": error or None,
            },
            ensure_ascii=False,
        ),
    )
