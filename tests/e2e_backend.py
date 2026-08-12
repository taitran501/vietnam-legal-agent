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
from epr_agent.agent.v4 import V4WorkflowRuntime
from epr_agent.domain.epr_rules import case_fields, missing_fact_keys
from epr_agent.domain.models import DocumentRecord
from epr_agent.domain.v4 import CaseStateV4, FactSource, FactValue
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import EvidenceGenerationGateway
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
def _legal_document(anchor: str) -> DocumentRecord:
    title = "Phụ lục XXII - Tỷ lệ và quy cách tái chế" if anchor == "Phụ lục XXII" else "Nghị định 08/2022/NĐ-CP"
    content = (
        f"{anchor} quy định đối tượng, lộ trình và trách nhiệm tái chế đối với nhà sản xuất, "
        "nhập khẩu sản phẩm hoặc bao bì đưa ra thị trường Việt Nam. "
    ) * 4
    return DocumentRecord(
        content=content,
        metadata={
            "Dieu": anchor if anchor.startswith("Điều") else "",
            "Parent_Dieu": anchor if anchor.startswith("Điều") else "",
            "legal_anchor": anchor,
            "Document_Number": "08/2022/NĐ-CP",
            "source": title,
            "source_title": title,
            "source_file": "data/08_2022_ND-CP_479457.doc",
            "Corpus_Version": "browser-e2e-v4",
            "Corpus_SHA256": "browser-e2e-corpus-v4",
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
        },
        document_id=f"law-{anchor.replace(' ', '-')}",
        score=0.94,
        source="legal",
    )


legal_documents = [_legal_document(f"Điều {article}") for article in range(77, 93)] + [_legal_document("Phụ lục XXII")]
dependencies = WorkflowDependencies(
    history=history,
    cache=ScopedAnswerCache(InMemoryAnswerCache(), corpus_version="browser-e2e"),
    retrieval=StaticRetrievalGateway(legal_documents=legal_documents),
    evidence=EvidenceEvaluator(min_chars=20),
    generation=EvidenceGenerationGateway(),
    planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
)

app = FastAPI(title="EPR deterministic browser acceptance")
app.state.workflow_runtime = V4WorkflowRuntime(
    dependencies,
    answer_chunk_size=90,
    answer_chunk_delay_s=0.04,
)
app.include_router(chat_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/ready")
async def ready() -> dict[str, object]:
    """Frontend readiness contract for deterministic browser acceptance."""

    payload, _ = await _deterministic_ready()
    return payload


@app.get("/api/v1/sessions/{session_id}/case")
async def get_case(session_id: str) -> dict[str, Any] | None:
    return await history.get_case("dev-local", session_id)


@app.patch("/api/v1/sessions/{session_id}/case")
async def update_case(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Deterministic case-panel adapter used by the real browser suite."""

    existing = await history.get_case("dev-local", session_id) or {}
    task_type = str(body.get("task_type") or existing.get("task_type") or "assess_epr_obligation")
    raw_facts = dict(body.get("facts") or {})
    facts = {
        key: FactValue(value=str(value), source=FactSource.CASE_PANEL, verified=True)
        for key, value in raw_facts.items()
        if str(value).strip()
    }
    missing = missing_fact_keys(facts)
    case = CaseStateV4(
        task_type=task_type,
        status="ready" if not missing else "collecting",
        facts=facts,
        missing_facts=missing,
        last_query=str(existing.get("last_query") or ""),
    )
    payload = case.model_dump(mode="json")
    payload["fields"] = [field.model_dump() for field in case_fields(facts, missing)]
    return await history.save_case("dev-local", session_id, payload)


@app.get("/api/v1/sessions")
async def sessions() -> list[dict[str, Any]]:
    return []
