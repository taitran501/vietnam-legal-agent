"""Deterministic adapters shared by Pipeline V4 behavior tests."""

from __future__ import annotations

from typing import Any

from vietnam_legal_agent.agent.graph import WorkflowDependencies
from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.agent.v4 import V4WorkflowRuntime
from vietnam_legal_agent.domain.legal import explicit_anchors
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway, StaticGenerationGateway
from vietnam_legal_agent.tools.history import ContextSnapshot
from vietnam_legal_agent.tools.legal_readiness import SyntheticReadyLegalReadinessGate
from vietnam_legal_agent.tools.retrieval import RetrievalGateway


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
    title, body = {
        "Điều 30": (
            "Luật Giao thông đường bộ",
            "Người điều khiển và người ngồi trên xe mô tô phải tuân thủ quy tắc an toàn giao thông.",
        ),
        "Điều 48": (
            "Bộ luật Lao động 2019",
            "Khi chấm dứt hợp đồng lao động, các bên thực hiện trách nhiệm thanh toán và bàn giao.",
        ),
        "Điều 77": (
            "Luật Bảo vệ môi trường 2020",
            "Điều khoản quy định nguyên tắc quản lý môi trường và trách nhiệm của tổ chức, cá nhân.",
        ),
        "Điều 1": (
            "Luật Tài nguyên, môi trường biển và hải đảo 2015",
            "Luật quy định quản lý tổng hợp tài nguyên, bảo vệ môi trường biển và hải đảo, cùng quyền và nghĩa vụ liên quan.",
        ),
        "Điều 81": (
            "Luật Hôn nhân và Gia đình 2014",
            "Việc nuôi dưỡng con được xem xét trên cơ sở quyền lợi mọi mặt của con.",
        ),
        "Điều 94": (
            "Bộ luật Lao động 2019",
            "Người sử dụng lao động phải trả lương trực tiếp, đầy đủ và đúng hạn cho người lao động.",
        ),
        "Điều 111": (
            "Luật Doanh nghiệp 2020",
            "Công ty cổ phần có số lượng cổ đông tối thiểu theo quy định pháp luật doanh nghiệp.",
        ),
        "Điều 328": (
            "Bộ luật Dân sự 2015",
            "Tiền đặt cọc được xử lý theo thỏa thuận và quy định của pháp luật dân sự.",
        ),
    }.get(anchor, ("Bộ luật Dân sự 2015", "Quy định pháp luật áp dụng cho quyền và nghĩa vụ dân sự."))
    content = f"{anchor}. {body} {extra} " * 5
    document_number = (
        "82/2015/QH13"
        if anchor == "Điều 1" and title == "Luật Tài nguyên, môi trường biển và hải đảo 2015"
        else ""
    )
    return DocumentRecord(
        content=content,
        metadata={
            "Dieu": anchor if anchor.startswith("Điều") else "",
            "Parent_Dieu": anchor if anchor.startswith("Điều") else "",
            "legal_anchor": anchor,
            "Document_Number": document_number,
            "source": title,
            "source_title": title,
            "source_file": "universal-corpus",
            "Corpus_ID": "vietnamese_law",
            "Corpus_Version": "general-v4-test",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "provenance": "universal-corpus",
        },
        document_id=document_id or f"law-{anchor.replace(' ', '-').replace('ụ', 'u')}",
        score=0.94,
        source="legal",
    )


class IssueAwareRetrieval:
    """Return only evidence matching the typed request's required anchors."""

    def __init__(self, documents: list[DocumentRecord] | None = None) -> None:
        self.documents = documents if documents is not None else [
            legal_document(anchor)
            for anchor in ("Điều 1", "Điều 30", "Điều 48", "Điều 77", "Điều 81", "Điều 94", "Điều 111", "Điều 328")
        ]
        self.requests: list[Any] = []

    async def legal(self, request: Any) -> list[DocumentRecord]:
        self.requests.append(request)
        anchors = list(getattr(request, "required_anchors", []) or [])
        if isinstance(request, str):
            # Preserve explicit legal anchors while allowing broad retrieval
            # for ordinary queries that do not name a specific provision.
            anchors = list(
                dict.fromkeys(
                    anchor.key()
                    for anchor in explicit_anchors(request)
                    if anchor.article or anchor.appendix
                )
            )
        if not anchors:
            return list(self.documents)
        return [
            document
            for document in self.documents
            if any(
                " ".join(anchor.casefold().replace(" | ", " ").split()) in " ".join((
                    str(document.metadata.get("Document_Number") or "")
                    + " " + str(document.metadata.get("Instrument_Number") or "")
                    + " " + str(document.metadata.get("legal_anchor") or "")
                    + " " + str(document.metadata.get("Dieu") or "")
                    + " " + document.content
                ).casefold().split())
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
        if task_type not in {"case_assessment", "build_compliance_checklist"}:
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
        cache=ScopedAnswerCache(InMemoryAnswerCache(), corpus_version="general-v4-test"),
        retrieval=retrieval,
        evidence=EvidenceEvaluator(min_chars=20),
        generation=DocumentAwareGenerationGateway(),
        planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
        legal_readiness=SyntheticReadyLegalReadinessGate(),
    )
    return V4WorkflowRuntime(dependencies, answer_chunk_delay_s=answer_chunk_delay_s), history, retrieval
