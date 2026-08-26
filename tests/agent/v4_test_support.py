"""Deterministic adapters shared by Pipeline V4 behavior tests."""

from __future__ import annotations

import re
from typing import Any

from epr_agent.agent.graph import WorkflowDependencies
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.v4 import V4WorkflowRuntime
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import EvidenceGenerationGateway, StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import RetrievalGateway


class MemoryHistory:
    def __init__(self, active_case: dict[str, Any] | None = None) -> None:
        self.active_case = active_case
        self.messages: list[dict[str, Any]] = []
        self.saved_cases: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []

    async def initialize(self) -> None:
        return None

    async def load(self, _user_id: str, _conversation_id: str, _max_messages: int) -> ContextSnapshot:
        return ContextSnapshot(list(self.messages), self.active_case)

    async def save_case(self, _user_id: str, _conversation_id: str, state: dict[str, Any]) -> dict[str, Any]:
        self.active_case = dict(state)
        self.saved_cases.append(dict(state))
        return dict(state)

    async def clear_case(self, _user_id: str, _conversation_id: str) -> None:
        if self.active_case:
            self.active_case = {**self.active_case, "status": "completed", "missing_facts": []}

    async def save_exchange(self, _user_id: str, _conversation_id: str, user: str, assistant: str, metadata: dict[str, Any]) -> None:
        self.messages.extend([
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant, "metadata": metadata},
        ])

    async def record_run(self, state: dict[str, Any], _started_at: float, _ended_at: float) -> None:
        self.runs.append(dict(state))


def legal_document(anchor: str, *, extra: str = "", document_id: str | None = None) -> DocumentRecord:
    title = "Phụ lục XXII - Tỷ lệ và quy cách tái chế" if anchor == "Phụ lục XXII" else "Nghị định số 08/2022/NĐ-CP"
    content = f"{anchor}. Căn cứ pháp lý về trách nhiệm EPR và điều kiện áp dụng. {extra} " * 5
    return DocumentRecord(
        content=content,
        metadata={
            "Dieu": anchor if anchor.startswith("Điều") else "",
            "Parent_Dieu": anchor if anchor.startswith("Điều") else "",
            "legal_anchor": anchor,
            # Deterministic fixtures must carry the same typed provenance that
            # production evidence validation requires.  A title alone is not
            # sufficient to prove an instrument-number match.
            "instrument_number": "08/2022/NĐ-CP",
            "explicit_match": True,
            "source": title,
            "source_title": title,
            "source_file": "data/08_2022_ND-CP_479457.doc",
            "Corpus_Version": "epr-v4-test",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "provenance": "data/08_2022_ND-CP_479457.doc",
        },
        document_id=document_id or f"law-{anchor.replace(' ', '-').replace('ụ', 'u')}",
        score=0.94,
        source="legal",
    )


class IssueAwareRetrieval:
    """Return only evidence matching the typed request's required anchors."""

    def __init__(self, documents: list[DocumentRecord] | None = None) -> None:
        self.documents = documents if documents is not None else [
            *(legal_document(f"Điều {article}") for article in range(77, 93)),
            legal_document("Phụ lục XXII"),
        ]
        self.requests: list[Any] = []

    async def legal(self, request: Any) -> list[DocumentRecord]:
        self.requests.append(request)
        anchors = list(getattr(request, "required_anchors", []) or [])
        if isinstance(request, str):
            anchors = list(dict.fromkeys(re.findall(r"Điều\s+\d+", request, flags=re.IGNORECASE)))
        if not anchors:
            return list(self.documents)
        return [
            document
            for document in self.documents
            if any(
                anchor.casefold() in (
                    str(document.metadata.get("legal_anchor") or "")
                    + " " + str(document.metadata.get("Dieu") or "")
                    + " " + document.content
                ).casefold()
                for anchor in anchors
            )
        ]


class NoEvidenceRetrieval(IssueAwareRetrieval):
    async def legal(self, request: Any) -> list[DocumentRecord]:
        self.requests.append(request)
        return []


class DocumentAwareGenerationGateway(StaticGenerationGateway):
    """Generate source-aligned legal text for deterministic retrieval tests."""

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str:
        if task_type not in {"assess_epr_obligation", "build_compliance_checklist"}:
            return EvidenceGenerationGateway._compose_legal_route_answer(documents)
        return await super().answer(task_type, query, documents, facts)


def runtime(
    history: MemoryHistory | None = None,
    retrieval: RetrievalGateway | None = None,
    *,
    answer_chunk_delay_s: float = 0,
) -> tuple[V4WorkflowRuntime, MemoryHistory, RetrievalGateway]:
    history = history or MemoryHistory()
    retrieval = retrieval or IssueAwareRetrieval()
    dependencies = WorkflowDependencies(
        history=history,
        cache=ScopedAnswerCache(InMemoryAnswerCache(), corpus_version="epr-v4-test"),
        retrieval=retrieval,
        evidence=EvidenceEvaluator(min_chars=20),
        generation=DocumentAwareGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
    )
    return V4WorkflowRuntime(dependencies, answer_chunk_delay_s=answer_chunk_delay_s), history, retrieval
