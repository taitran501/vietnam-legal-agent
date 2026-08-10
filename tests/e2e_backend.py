"""Deterministic FastAPI host for browser-level frontend/backend acceptance.

This process exercises the production chat route, SSE presenter, LangGraph,
React SSE parser, and UI without requiring paid APIs or live infrastructure.
Only tool adapters are deterministic doubles.
"""

from __future__ import annotations

from typing import Any

from backend.api.routes import chat as chat_routes
from backend.api.routes.chat import router as chat_router
from fastapi import FastAPI

from epr_agent.agent.graph import WorkflowDependencies
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.runtime import WorkflowRuntime
from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


async def _deterministic_ready() -> tuple[dict[str, object], bool]:
    """Keep browser acceptance isolated from Docker/Qdrant readiness.

    The production router correctly checks the versioned corpus before every
    chat request.  This dedicated browser host exercises the same SSE route
    with deterministic adapters, so it supplies the ready contract without
    requiring the real local stack during UI tests.
    """

    return ({"status": "ready", "dependencies": {}, "corpus": {"status": "ready"}}, True)


chat_routes.readiness_payload = _deterministic_ready


class BrowserHistoryGateway:
    """Conversation-scoped in-memory history used only by Playwright."""

    def __init__(self) -> None:
        self.messages: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.cases: dict[tuple[str, str], dict[str, Any]] = {}
        self.runs: list[dict[str, Any]] = []

    async def initialize(self) -> None:
        return None

    async def load(self, user_id: str, conversation_id: str, max_messages: int) -> ContextSnapshot:
        key = (user_id, conversation_id)
        return ContextSnapshot(
            history=list(self.messages.get(key, []))[-max_messages:],
            active_case=self.cases.get(key),
        )

    async def save_exchange(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
    ) -> None:
        key = (user_id, conversation_id)
        conversation = self.messages.setdefault(key, [])
        conversation.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message, "metadata": metadata},
            ]
        )

    async def save_case(
        self,
        user_id: str,
        conversation_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        saved = {
            **state,
            "status": "collecting" if state.get("missing_facts") else "ready",
        }
        self.cases[(user_id, conversation_id)] = saved
        return saved

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        case = self.cases.get((user_id, conversation_id))
        if case:
            case.update({"status": "completed", "missing_facts": []})

    async def get_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        return self.cases.get((user_id, conversation_id))

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        self.runs.append(dict(state))


history = BrowserHistoryGateway()
legal_document = DocumentRecord(
    content=(
        "Điều 77 quy định đối tượng, lộ trình và trách nhiệm tái chế đối với nhà sản xuất, "
        "nhập khẩu sản phẩm hoặc bao bì đưa ra thị trường Việt Nam. "
    )
    * 4,
    metadata={
        "Dieu": "Điều 77",
        "Parent_Dieu": "Điều 77",
        "legal_anchor": "08/2022/NĐ-CP | Điều 77",
        "Document_Number": "08/2022/NĐ-CP",
        "source": "Nghị định 08/2022/NĐ-CP",
        "source_file": "data/08_2022_ND-CP_479457.doc",
        "Corpus_Version": "browser-e2e-v3",
        "Corpus_SHA256": "browser-e2e-corpus",
        "Embedding_Profile": "openai-text-embedding-3-small-v1",
    },
    document_id="law-77",
    score=0.94,
    source="legal",
)
dependencies = WorkflowDependencies(
    history=history,
    cache=ScopedAnswerCache(InMemoryAnswerCache(), corpus_version="browser-e2e"),
    retrieval=StaticRetrievalGateway(legal_documents=[legal_document]),
    evidence=EvidenceEvaluator(min_chars=20),
    generation=StaticGenerationGateway("Theo Điều 77 [1], nhà sản xuất và nhập khẩu phải đối chiếu trách nhiệm tái chế."),
    planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
)

app = FastAPI(title="EPR deterministic browser acceptance")
app.state.workflow_runtime = WorkflowRuntime(dependencies)
app.include_router(chat_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/ready")
async def ready() -> dict[str, object]:
    """Frontend readiness contract for deterministic browser acceptance."""

    payload, _ = await _deterministic_ready()
    return payload


@app.get("/api/v1/sessions")
async def sessions() -> list[dict[str, Any]]:
    return []
