"""Streaming presenter for the bounded workflow."""

from __future__ import annotations

import logging
import re
from typing import Any

from vietnam_legal_agent.domain.models import AgentState, TaskType, TerminationReason
from vietnam_legal_agent.tools.source_provenance import (
    canonical_source_snapshots,
    normalize_source,
    normalized_document_metadata,
)

logger = logging.getLogger(__name__)


_ACTION_STATUS = {
    "validate_input": "Đã kiểm tra nội dung câu hỏi.",
    "load_context": "Đã nạp lịch sử và trạng thái tình huống.",
    "understand_task": "Đã hiểu yêu cầu và kiểm tra thông tin đầu vào.",
    "check_cache": "Đã kiểm tra câu trả lời có thể tái sử dụng.",
    "answer_cache": "Đã xác minh câu trả lời từ bộ nhớ đệm.",
    "ask_user": "Cần thêm thông tin trước khi tiếp tục.",
    "retrieve_legal": "Đã truy xuất tài liệu pháp luật.",
    "evaluate_evidence": "Đã đánh giá mức độ đầy đủ của bằng chứng.",
    "retrieve_web": "Đã kiểm tra nguồn pháp luật chính thức trên web.",
    "compose_answer": "Đã soạn câu trả lời dựa trên bằng chứng.",
    "verify_citations": "Đã kiểm tra trích dẫn và điều luật.",
    "repair_answer": "Đã sửa câu trả lời theo nguồn đã truy xuất.",
    "finish": "Workflow đã hoàn tất.",
    "safe_stop": "Workflow đã dừng an toàn.",
}


def split_verified_answer_for_stream(answer: str, *, max_chunk_chars: int = 180) -> list[str]:
    """Split an already verified answer into display-sized SSE chunks.

    The workflow intentionally does not emit legal claims while citation
    verification is still pending.  Once the verifier has accepted the final
    answer, this helper preserves the exact text while producing enough
    bounded chunks for the client to render progressive output.
    """

    if not answer:
        return []
    if max_chunk_chars < 1:
        raise ValueError("max_chunk_chars must be positive")

    chunks: list[str] = []
    current = ""
    for token in re.findall(r"\S+(?:\s+|$)", answer):
        # A long URL or legal identifier should never block streaming.
        while len(token) > max_chunk_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(token[:max_chunk_chars])
            token = token[max_chunk_chars:]
        if current and len(current) + len(token) > max_chunk_chars:
            chunks.append(current)
            current = token
        else:
            current += token
    if current:
        chunks.append(current)
    return chunks


def _cited_evidence_indices(answer: str, evidence: list[dict[str, Any]]) -> set[int]:
    """Return citation indices referenced by an answer, bounded to the evidence range.

    The answer text may contain bracketed numbers that are not citations (for
    example years like ``[2023]`` or article counts).  Only indices that point
    at an actual evidence item are treated as citations; anything else would
    otherwise hide every source from the source drawer.
    """

    if not evidence:
        return set()
    return {int(value) for value in re.findall(r"\[(\d+)\]", answer or "") if 1 <= int(value) <= len(evidence)}


def _documents_for_api(state: AgentState) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    used_indices = _cited_evidence_indices(state.get("answer", ""), list(state.get("evidence", [])))
    for citation_index, item in enumerate(state.get("evidence", []), start=1):
        if used_indices and citation_index not in used_indices:
            continue
        excerpt_limit = 1200 if item.get("source") == "web" else 2000
        snapshot = normalize_source(
            item,
            citation_index=citation_index,
            corpus_as_of_date=str(state.get("corpus_as_of_date") or ""),
            excerpt_limit=excerpt_limit,
        )
        safe_metadata = normalized_document_metadata(snapshot, original=item)
        documents.append(
            {
                "page_content": str(snapshot.get("excerpt") or ""),
                "metadata": safe_metadata,
                # Keep the chunk id in the legacy field so citation indices and
                # answer verification remain stable.  The canonical parent
                # document id is available as metadata.source_id.
                "document_id": snapshot.get("chunk_id") or item.get("document_id", ""),
                "score": item.get("score"),
                "source": snapshot.get("source_kind") or item.get("source", ""),
            }
        )
    return documents


def _source_snapshots(state: AgentState) -> list[dict[str, Any]]:
    used_indices = _cited_evidence_indices(state.get("answer", ""), list(state.get("evidence", [])))
    evidence = list(state.get("evidence", []))
    selected = [
        (citation_index, item)
        for citation_index, item in enumerate(evidence, start=1)
        if not used_indices or citation_index in used_indices
    ]
    if not selected:
        return []
    return canonical_source_snapshots(
        [item for _, item in selected],
        citation_indices=[citation_index for citation_index, _ in selected],
        corpus_as_of_date=str(state.get("corpus_as_of_date") or ""),
        excerpt_limit=1200 if any(item.get("source") == "web" for _, item in selected) else 2000,
    )


def _metadata(state: AgentState) -> dict[str, Any]:
    checklist = state.get("checklist", [])
    history = state.get("history") or []
    assumptions = [item.get("assumption") for item in checklist if item.get("assumption")]
    if state.get("assessment"):
        assumptions.extend(item for item in (state.get("assessment") or {}).get("assumptions", []) if item)
        if not assumptions:
            assumptions.append("Kết quả đánh giá là sơ bộ và phụ thuộc vào thông tin doanh nghiệp đã cung cấp.")
    return {
        "task_type": state.get("task_type", TaskType.LEGAL_LOOKUP.value),
        "route": state.get("route", "legal_lookup"),
        "context_loaded": bool(state.get("context_loaded", False)),
        "history_messages": int(state.get("history_messages", len(history))),
        "is_follow_up": bool(state.get("is_follow_up", False)),
        "standalone_query": state.get("standalone_query", state.get("query", "")),
        "source_scope": state.get("source_scope", "legal_corpus"),
        "corpus_version": state.get("corpus_version", ""),
        "corpus_sha": state.get("corpus_sha", ""),
        "embedding_profile": state.get("embedding_profile", ""),
        "evidence_status": state.get("evidence_status", "not_evaluated"),
        "available_actions": state.get("available_actions", []),
        "assessment": state.get("assessment"),
        "checklist": checklist,
        "assumptions": assumptions,
        "missing_facts": state.get("missing_facts", []),
        "citations": state.get("citations", []),
        "evidence_assessment": state.get("evidence_assessment", {}),
        "trace_id": state.get("trace_id", ""),
        "corpus_id": state.get("corpus_id", "vietnamese_law"),
        "corpus_as_of_date": state.get("corpus_as_of_date", ""),
        "preview": bool(state.get("preview", False)),
        "pipeline_version": state.get("pipeline_version", "pipeline-v4"),
        "termination_reason": state.get("termination_reason") or TerminationReason.ERROR.value,
        "outcome": state.get("outcome"),
        "result_type": state.get("result_type"),
        "required_issues": state.get("required_issues", []),
        "covered_issues": state.get("covered_issues", []),
        "assistant_message_id": state.get("assistant_message_id", ""),
        "sources": state.get("sources") or _source_snapshots(state),
        "replay_metadata": state.get("replay_metadata") or {},
        "rule_id": state.get("rule_id", ""),
        "citation_error": state.get("citation_error", ""),
        "safe_stop_reason": state.get("safe_stop_reason", ""),
        "verification_status": state.get("verification_status", ""),
        "legal_readiness_status": state.get("legal_readiness_status", ""),
        "legal_readiness_sha": state.get("legal_readiness_sha", ""),
    }
