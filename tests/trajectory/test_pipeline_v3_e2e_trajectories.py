"""Execute every Pipeline V3 trajectory through the bounded LangGraph runtime.

This suite is deliberately deterministic: it validates route boundaries,
history/case resumption, evidence gates, citations, repair limits, and timing
without making the regular local test run dependent on OpenAI or Tavily.
The separate live retrieval evaluator exercises the real Qdrant index.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.eval.pipeline_v3_manifest import E2E_TRAJECTORIES

from epr_agent.agent.graph import WorkflowDependencies
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.runtime import WorkflowRuntime
from epr_agent.domain.legal import explicit_anchors
from epr_agent.domain.models import AgentState, DocumentRecord
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import StaticGenerationGateway
from epr_agent.tools.history import ContextSnapshot


class TrajectoryHistory:
    """Small stateful history adapter used to exercise multi-turn case state."""

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
        conversation = self.messages.setdefault((user_id, conversation_id), [])
        conversation.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message, "metadata": metadata},
            ]
        )

    async def save_case(self, user_id: str, conversation_id: str, state: dict[str, Any]) -> dict[str, Any]:
        saved = {**state, "status": "collecting" if state.get("missing_facts") else "ready"}
        self.cases[(user_id, conversation_id)] = saved
        return saved

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        case = self.cases.get((user_id, conversation_id))
        if case:
            case.update({"status": "completed", "missing_facts": []})

    async def get_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        return self.cases.get((user_id, conversation_id))

    async def record_run(self, state: AgentState, started_at: float, ended_at: float) -> None:
        self.runs.append(dict(state))


class ManifestRetrievalGateway:
    """Return only source-backed chunks that the manifest query can support."""

    _NO_EVIDENCE = (
        "quốc gia khác",
        "chưa có trong corpus",
        "điều 999",
        "quy định epr của eu",
    )

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def legal(self, query: str) -> list[DocumentRecord]:
        self.calls.append(query)
        normalized = " ".join(query.lower().split())
        if any(marker in normalized for marker in self._NO_EVIDENCE):
            return []
        articles = [anchor.article for anchor in explicit_anchors(query) if anchor.article]
        return [self._document(article) for article in (articles or ["Điều 77"])]

    @staticmethod
    def _document(article: str) -> DocumentRecord:
        return DocumentRecord(
            content=(
                f"{article} quy định nội dung pháp luật EPR cần được đối chiếu theo "
                "văn bản gốc, phạm vi áp dụng và trách nhiệm liên quan. "
            ) * 4,
            metadata={
                "Dieu": article,
                "Parent_Dieu": article,
                "legal_anchor": f"08/2022/NĐ-CP | {article}",
                "Document_Number": "08/2022/NĐ-CP",
                "source": "Nghị định 08/2022/NĐ-CP",
                "source_file": "data/08_2022_ND-CP_479457.doc",
                "Corpus_Version": "trajectory-v3",
                "Corpus_SHA256": "a" * 64,
                "Embedding_Profile": "openai-text-embedding-3-small-v1",
                "rerank_score": 0.95,
            },
            document_id=f"trajectory:{article}",
            source="legal",
            score=0.95,
        )


def _runtime(history: TrajectoryHistory, *, repair: bool) -> WorkflowRuntime:
    generation = StaticGenerationGateway(
        "Kết luận này cần được kiểm tra thêm."
        if repair
        else "Quy định cần được đối chiếu theo tài liệu nguồn [1]."
    )
    dependencies = WorkflowDependencies(
        history=history,
        cache=ScopedAnswerCache(InMemoryAnswerCache(), corpus_version="trajectory-v3"),
        retrieval=ManifestRetrievalGateway(),
        evidence=EvidenceEvaluator(min_chars=20),
        generation=generation,
        planner=BoundedPlanner(max_retrieval_actions=2, max_repairs=1, max_iterations=12),
    )
    return WorkflowRuntime(dependencies)


def _expected_termination(case: dict[str, object]) -> str:
    if "expected_termination" in case:
        return str(case["expected_termination"])
    return "research_complete" if case["expected_route"] == "research_web" else "answer_complete"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", E2E_TRAJECTORIES, ids=lambda case: str(case["id"]))
async def test_pipeline_v3_trajectory_contract(case: dict[str, object]) -> None:
    history = TrajectoryHistory()
    runtime = _runtime(history, repair=bool(case.get("requires_repair")))
    conversation_id = f"trajectory-{case['id']}"

    for prelude in case.get("prelude", []):
        await runtime.run(
            query=str(prelude),
            user_id="trajectory-owner",
            conversation_id=conversation_id,
        )

    state = await runtime.run(
        query=str(case["query"]),
        user_id="trajectory-owner",
        conversation_id=conversation_id,
        mode=str(case.get("mode", "auto")),
    )

    assert state["route"] == case["expected_route"]
    assert state["termination_reason"] == _expected_termination(case)
    assert state["run_duration_ms"] < 15_000
    assert state["trace_id"]
    assert state["trace_events"]
    assert state["retrieval_actions"] <= 2
    assert state["repair_count"] <= 1
    assert not any("faq" in action for action in state["action_sequence"])

    if state["route"] != "research_web":
        assert "retrieve_web" not in state["action_sequence"]
    if state["termination_reason"] == "awaiting_user_input":
        assert state["missing_facts"]
        assert "retrieve_legal" not in state["action_sequence"]
    if state["termination_reason"] == "insufficient_evidence":
        assert state["available_actions"] == ["research_web"]
        assert not state["citation_valid"]
    if state["termination_reason"] == "answer_complete" and state["route"] != "chitchat":
        assert state["citations"]
        assert state["citation_valid"]
    if case.get("requires_repair"):
        assert state["repair_count"] == 1
