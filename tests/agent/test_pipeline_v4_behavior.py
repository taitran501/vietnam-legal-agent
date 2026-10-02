"""Behavior contracts for the V4 case workflow.

These tests assert decisions and visible outcome states, rather than brittle
generated prose.  They are the regression guard for the incorrect generic
assessment shown by the old quick-action flow.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from vietnam_legal_agent.agent.graph import WorkflowDependencies
from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.agent.understanding import StaticTaskUnderstandingGateway
from vietnam_legal_agent.agent.v4 import V4WorkflowRuntime
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.domain.routes import RouteType
from vietnam_legal_agent.domain.tasks import TaskUnderstanding
from vietnam_legal_agent.retrieval.universal_retriever import UniversalLegalRetriever
from vietnam_legal_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway, StaticGenerationGateway
from vietnam_legal_agent.tools.history import ContextSnapshot
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway, UniversalLegalRetrievalGateway


class MemoryHistory:
    def __init__(self) -> None:
        self.case: dict | None = None
        self.messages: list[dict[str, Any]] = []

    async def initialize(self):
        return None

    async def load(self, *_args):
        return ContextSnapshot(list(self.messages), self.case)

    async def save_case(self, _user, _conversation, state):
        self.case = dict(state)
        return self.case

    async def clear_case(self, *_args):
        if self.case:
            self.case["status"] = "completed"

    async def save_exchange(self, *_args):
        return None

    async def record_run(self, *_args):
        return None


def legal_document(anchor: str) -> DocumentRecord:
    title, body = {
        "Điều 30": ("Luật Giao thông đường bộ", "Người điều khiển và người ngồi trên xe mô tô phải đội mũ bảo hiểm."),
        "Điều 48": ("Bộ luật Lao động 2019", "Khi chấm dứt hợp đồng lao động, các bên thanh toán quyền lợi và bàn giao."),
        "Điều 4": ("Luật Bảo vệ môi trường 2020", "Bảo vệ môi trường là quyền, nghĩa vụ và trách nhiệm của mọi tổ chức, cộng đồng, hộ gia đình và cá nhân."),
        "Điều 81": ("Luật Hôn nhân và Gia đình 2014", "Việc nuôi dưỡng con được xem xét trên cơ sở quyền lợi mọi mặt của con."),
        "Điều 94": ("Bộ luật Lao động 2019", "Người sử dụng lao động phải trả lương đầy đủ, trực tiếp và đúng hạn."),
        "Điều 111": ("Luật Doanh nghiệp 2020", "Công ty cổ phần có ít nhất ba cổ đông và không hạn chế số lượng tối đa."),
        "Điều 328": ("Bộ luật Dân sự 2015", "Tiền đặt cọc được xử lý theo thỏa thuận và quy định của pháp luật dân sự."),
    }.get(anchor, ("Bộ luật Dân sự 2015", "Quy định pháp luật áp dụng cho quyền và nghĩa vụ dân sự."))
    return DocumentRecord(
        content=f"{anchor}. {body} " * 6,
        metadata={
            "Dieu": anchor if anchor.startswith("Điều") else "",
            "legal_anchor": anchor,
            "source": title,
            "source_title": title,
            "source_file": "universal-corpus",
            "Corpus_Version": "general-v4-test",
            "Corpus_SHA256": "a" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "provenance": "universal-corpus",
        },
        document_id=f"doc-{anchor.replace(' ', '-').replace('ụ', 'u')}",
        source="legal",
    )


class RelevantStaticRetrievalGateway(StaticRetrievalGateway):
    """Rank mock evidence by query overlap, as a retrieval adapter should."""

    async def legal(self, query: str | Any) -> list[DocumentRecord]:
        documents = await super().legal(query)
        query_text = str(getattr(query, "query", query) or "").casefold()
        query_terms = set(re.findall(r"[\wÀ-ỹĐđ]+", query_text)) - {"của", "có", "là", "và", "theo", "điều"}

        def relevance(document: DocumentRecord) -> int:
            metadata = document.metadata or {}
            source_text = " ".join(
                [
                    str(metadata.get("source_title") or ""),
                    str(metadata.get("source") or ""),
                    document.content,
                ]
            ).casefold()
            return sum(term in source_text for term in query_terms)

        return sorted(documents, key=relevance, reverse=True)


def runtime(history: MemoryHistory) -> tuple[V4WorkflowRuntime, StaticRetrievalGateway]:
    retrieval = RelevantStaticRetrievalGateway(
        legal_documents=[
            legal_document(anchor)
            for anchor in ("Điều 30", "Điều 48", "Điều 4", "Điều 81", "Điều 94", "Điều 111", "Điều 328")
        ]
    )
    deps = WorkflowDependencies(
        history=history,
        cache=ScopedAnswerCache(InMemoryAnswerCache()),
        retrieval=retrieval,
        evidence=EvidenceEvaluator(min_chars=20),
        generation=StaticGenerationGateway(),
        planner=BoundedPlanner(),
    )
    return V4WorkflowRuntime(deps, answer_chunk_delay_s=0), retrieval


def general_legal_document(anchor: str, *, title: str) -> DocumentRecord:
    return DocumentRecord(
        content=f"{anchor}. Căn cứ quy định pháp luật. " * 6,
        metadata={
            "Dieu": anchor,
            "legal_anchor": anchor,
            "source": title,
            "source_title": title,
            "source_file": "data/corpus.docx",
            "Corpus_Version": "vietnam-v4-test",
            "Corpus_SHA256": "b" * 64,
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "provenance": "data/corpus.docx",
        },
        document_id=f"doc-{anchor.replace(' ', '-').replace('ụ', 'u')}",
        source="legal",
    )


@pytest.mark.asyncio
async def test_situation_prompt_uses_ordinary_evidence_workflow_without_case_form():
    history = MemoryHistory()
    app, retrieval = runtime(history)
    state = await app.run(
        query="Tôi bị công ty chậm trả lương hai tháng, tôi có quyền gì?",
        user_id="v4-user", conversation_id="v4-case", intent_hint="case_assessment", interaction_source="quick_action",
    )
    assert state["route"] == "legal_lookup"
    assert state["task_type"] == "legal_lookup"
    assert state["outcome"] == "completed"
    assert state["result_type"] == "legal_answer"
    assert state["missing_facts"] == []
    assert state["case_state"] is None
    assert retrieval.calls
    assert history.case is None


@pytest.mark.asyncio
async def test_factual_corporate_question_uses_lookup_route_not_case_form():
    history = MemoryHistory()
    app, retrieval = runtime(history)
    state = await app.run(
        query="Luật Doanh nghiệp quy định công ty cổ phần cần tối thiểu bao nhiêu cổ đông sáng lập?",
        user_id="v4-user",
        conversation_id="v4-corporate-factual",
    )

    assert state["route"] == "legal_lookup"
    assert state["task_type"] == "legal_lookup"
    assert state.get("missing_facts") == []
    assert retrieval.calls == [("legal", state["query"])]


@pytest.mark.asyncio
async def test_case_understanding_conflict_continues_through_ordinary_lookup():
    query = "Công ty chậm trả lương thì người lao động có quyền gì?"
    history = MemoryHistory()
    app, retrieval = runtime(history)
    app.deps.understanding = StaticTaskUnderstandingGateway(
        TaskUnderstanding(
            task_type="case_assessment",
            route=RouteType.CASE_ASSESSMENT,
            standalone_query=query,
            confidence=1.0,
        )
    )

    state = await app.run(
        query=query,
        user_id="v4-user",
        conversation_id="v4-conflicting-understanding",
    )

    assert state["route"] == RouteType.LEGAL_LOOKUP.value
    assert state["task_type"] == "legal_lookup"
    assert state["outcome"] == "completed"
    assert state["termination_reason"] == "answer_complete"
    assert retrieval.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("intent_hint", ["auto", "case_assessment"])
async def test_personal_case_preserves_model_retrieval_rewrite(intent_hint: str):
    query = "Tôi mua hàng online, shop giao hàng khác hình và từ chối đổi trả thì quyền của tôi là gì?"
    rewrite = "quyền của người tiêu dùng khi mua hàng online"
    history = MemoryHistory()
    app, retrieval = runtime(history)
    understanding = StaticTaskUnderstandingGateway(
        TaskUnderstanding(
            task_type="case_assessment",
            route=RouteType.CASE_ASSESSMENT,
            standalone_query=query,
            retrieval_queries=[rewrite],
            confidence=1.0,
        )
    )
    app.deps.understanding = understanding

    state = await app.run(
        query=query,
        user_id="v4-user",
        conversation_id=f"v4-case-retrieval-{intent_hint}",
        intent_hint=intent_hint,
    )

    assert state["termination_reason"] == "answer_complete"
    assert understanding.calls == 1
    assert [search_query for _kind, search_query in retrieval.calls] == [query, rewrite]


@pytest.mark.asyncio
async def test_v4_reuses_route_understanding_plan_for_delegated_legal_lookup():
    history = MemoryHistory()
    app, retrieval = runtime(history)
    understanding = StaticTaskUnderstandingGateway(
        TaskUnderstanding(
            task_type="legal_lookup",
            route=RouteType.LEGAL_LOOKUP,
            standalone_query="Công ty cổ phần cần tối thiểu bao nhiêu cổ đông?",
            retrieval_queries=["số cổ đông tối thiểu công ty cổ phần", "Điều 111 Luật Doanh nghiệp"],
            confidence=1.0,
        )
    )
    app.deps.understanding = understanding

    state = await app.run(
        query="Công ty cổ phần cần tối thiểu bao nhiêu cổ đông?",
        user_id="v4-user",
        conversation_id="v4-plan-reuse",
    )

    assert state["termination_reason"] == "answer_complete"
    assert understanding.calls == 1
    assert len(retrieval.calls) == 2


@pytest.mark.asyncio
async def test_chitchat_completion_is_not_persisted_as_a_legal_answer():
    app, retrieval = runtime(MemoryHistory())

    state = await app.run(
        query="Xin chào, bạn có thể giúp tôi việc gì?",
        user_id="v4-user",
        conversation_id="v4-greeting",
    )

    assert state["route"] == "chitchat"
    assert state["outcome"] == "completed"
    assert state["result_type"] == "none"
    assert state["source"] == "chitchat"
    assert retrieval.calls == []


@pytest.mark.asyncio
async def test_unknown_non_legal_question_safe_stops_without_retrieval():
    history = MemoryHistory()
    app, retrieval = runtime(history)
    state = await app.run(
        query="Giá Bitcoin hôm nay là bao nhiêu?",
        user_id="v4-user",
        conversation_id="v4-bitcoin",
    )

    assert state["route"] == "out_of_scope"
    assert state["termination_reason"] == "out_of_scope"
    assert state["evidence"] == []
    assert retrieval.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("intent_hint", ["auto", "case_assessment"])
async def test_v4_clarifies_context_follow_up_after_unresolved_turn(intent_hint: str):
    history = MemoryHistory()
    history.messages = [
        {"role": "user", "content": "2026 có luật gì mới không?", "metadata": {}},
        {
            "role": "assistant",
            "content": "Tôi chưa tìm thấy căn cứ phù hợp.",
            "metadata": {"termination_reason": "insufficient_evidence"},
        },
    ]
    app, retrieval = runtime(history)

    state = await app.run(
        query="còn gì nữa?",
        user_id="v4-user",
        conversation_id="v4-follow-up",
        intent_hint=intent_hint,
    )

    assert state["route"] == "legal_lookup"
    assert state["source"] == "follow_up"
    assert state["termination_reason"] == "awaiting_user_input"
    assert state["outcome"] == "needs_information"
    assert state["clarification_required"] is True
    assert state["is_follow_up"] is True
    assert retrieval.requests == []


@pytest.mark.asyncio
async def test_v4_clarifies_context_dependent_query_without_history():
    app, retrieval = runtime(MemoryHistory())

    state = await app.run(
        query="còn gì nữa?",
        user_id="v4-user",
        conversation_id="v4-no-context",
    )

    assert state["termination_reason"] == "awaiting_user_input"
    assert state["history_messages"] == 0
    assert state["is_follow_up"] is True
    assert retrieval.requests == []


@pytest.mark.asyncio
async def test_environmental_topic_uses_the_general_legal_retriever():
    history = MemoryHistory()
    app, retrieval = runtime(history)
    state = await app.run(
        query="Trách nhiệm môi trường của doanh nghiệp được quy định ở đâu?",
        user_id="v4-user", conversation_id="v4-complete", intent_hint="case_assessment",
    )
    assert state["outcome"] == "completed", (state["evidence_assessment"], state["issue_states"])
    assert state["route"] == "legal_lookup"
    assert state["case_state"] is None
    assert state["rule_id"] == ""
    assert not state.get("rule_pack_version")
    assert not state.get("required_issues")
    assert not state.get("covered_issues")
    assert retrieval.calls
    assert all(request.issue_id == "legal_lookup" for request in retrieval.requests)


@pytest.mark.asyncio
async def test_producer_recycling_question_uses_ordinary_legal_chat_and_citations():
    if not UniversalLegalRetriever().is_available:
        pytest.skip("Universal legal corpus database is not built in this environment.")

    app, _ = runtime(MemoryHistory())
    app.deps.retrieval = UniversalLegalRetrievalGateway()

    state = await app.run(
        query="Nhà sản xuất có trách nhiệm tái chế sản phẩm và bao bì thế nào theo Luật Bảo vệ môi trường?",
        user_id="v4-user",
        conversation_id="v4-producer-recycling",
    )

    assert state["route"] == RouteType.LEGAL_LOOKUP.value
    assert state["task_type"] == "legal_lookup"
    assert state["outcome"] == "completed"
    assert state["result_type"] == "legal_answer"
    assert state["termination_reason"] == "answer_complete"
    assert not state.get("safe_stop_reason")
    assert "Điều 54" in state["answer"]
    assert state["evidence"]
    assert state["evidence"][0]["metadata"]["source_article"] == "Điều 54"
    assert state["citations"]


def test_extractive_fallback_skips_oversized_records_without_crashing():
    oversized = legal_document("Điều 1")
    oversized.content = "Điều 1. Nội dung sửa đổi và điều kiện áp dụng. " * 500
    relevant = legal_document("Điều 94")

    answer = EvidenceGenerationGateway._compose_legal_route_answer([oversized, relevant])
    limited_answer = EvidenceGenerationGateway._compose_legal_route_answer([oversized])

    assert "[2]" in answer
    assert "[1]" not in answer
    assert "quá dài để tóm tắt" in limited_answer
    assert "[1]" in limited_answer


@pytest.mark.asyncio
async def test_one_relevant_source_is_enough_for_general_legal_chat():
    history = MemoryHistory()
    app, retrieval = runtime(history)
    retrieval.legal_documents = [legal_document("Điều 94")]
    state = await app.run(
        query="Tôi bị công ty chậm trả lương, tôi có quyền gì?",
        user_id="v4-user", conversation_id="v4-no-appendix", intent_hint="case_assessment",
    )
    assert state["outcome"] == "completed"
    assert state["result_type"] == "legal_answer"
    assert state["termination_reason"] == "answer_complete"
    assert state["case_state"] is None


@pytest.mark.asyncio
async def test_v4_sse_does_not_emit_form_events_for_case_assessment():
    history = MemoryHistory()
    app, _ = runtime(history)
    events = [
        event
        async for event in app.stream(
            query="Tôi bị công ty chậm trả lương hai tháng, tôi có quyền gì?",
            user_id="v4-user",
            conversation_id="v4-sse",
            intent_hint="case_assessment",
            interaction_source="quick_action",
        )
    ]
    event_types = [event["type"] for event in events]
    assert "input_required" not in event_types
    assert "case_update" not in event_types
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert {event["trace_id"] for event in events} == {events[0]["trace_id"]}
    assert {event["pipeline_version"] for event in events} == {"pipeline-v4"}
    steps = [event for event in events if event["type"] == "workflow_step"]
    assert steps[0]["action"] == "understand_task"
    assert steps[0]["status"] == "running"
    complete = next(event for event in events if event["type"] == "response_complete")
    assert complete["outcome"] == "completed"
    assert complete["result_type"] == "legal_answer"
    assert complete["pipeline_version"] == "pipeline-v4"
    assert "case_state" not in complete


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["Hướng dẫn cách nấu phở bò Nam Định?", "Kết quả bóng đá Ngoại hạng Anh hôm nay?"])
async def test_v4_out_of_scope_stops_before_legacy_retrieval(query: str):
    history = MemoryHistory()
    app, retrieval = runtime(history)

    state = await app.run(query=query, user_id="v4-user", conversation_id="v4-out-of-scope")

    assert state["route"] == "out_of_scope"
    assert state["outcome"] == "out_of_scope"
    assert state["result_type"] == "none"
    assert state["termination_reason"] == "out_of_scope"
    assert retrieval.requests == []


@pytest.mark.asyncio
async def test_v4_explicit_no_evidence_signal_stops_without_claim():
    history = MemoryHistory()
    app, retrieval = runtime(history)

    state = await app.run(
        query="Thời hạn khởi kiện của nhóm chưa có trong corpus là bao lâu?",
        user_id="v4-user",
        conversation_id="v4-no-evidence-signal",
    )

    assert state["route"] == "legal_lookup"
    assert state["outcome"] == "insufficient_evidence"
    assert state["termination_reason"] == "insufficient_evidence"
    assert state["result_type"] == "none"
    assert state["available_actions"] == ["research_web"]
    assert retrieval.requests == []


@pytest.mark.asyncio
async def test_delegated_legal_lookup_preserves_replay_descriptor(monkeypatch: pytest.MonkeyPatch):
    history = MemoryHistory()
    app, _ = runtime(history)
    replay = {
        "query_mode": "auto",
        "intent": "legal_lookup",
        "operation": "message",
        "interaction_source": "composer",
        "test_context": "ordinary legal lookup",
    }

    async def fake_run_workflow(*args, **kwargs):
        return {
            "query": args[0],
            "user_id": kwargs["user_id"],
            "conversation_id": kwargs["conversation_id"],
            "trace_id": kwargs["trace_id"],
            "termination_reason": "answer_complete",
            "answer": "Điều 48 [1]",
            "source": "legal",
        }

    monkeypatch.setattr("vietnam_legal_agent.agent.v4.run_workflow", fake_run_workflow)
    state = await app._execute(
        query="Bộ luật Lao động Điều 94",
        user_id="v4-user",
        conversation_id="v4-replay",
        intent_hint="legal_lookup",
        interaction_source="composer",
        replay_metadata=replay,
    )

    assert state["replay_metadata"] == replay
    assert "case_patch" not in state
    assert "fact_updates" not in state
    assert state["pipeline_version"] == "pipeline-v4"


@pytest.mark.asyncio
async def test_general_case_uses_ordinary_evidence_lookup_without_fixed_form(monkeypatch: pytest.MonkeyPatch):
    history = MemoryHistory()
    app, _retrieval = runtime(history)
    observed: dict[str, Any] = {}

    async def fake_run_workflow(query: str, **kwargs: Any):
        observed["query"] = query
        observed["plan"] = kwargs["precomputed_understanding"]
        return {
            "query": query,
            "user_id": kwargs["user_id"],
            "conversation_id": kwargs["conversation_id"],
            "trace_id": kwargs["trace_id"],
            "termination_reason": "answer_complete",
            "answer": "Tôi đã đối chiếu căn cứ pháp luật được truy xuất. [1]",
            "source": "legal",
            "evidence": [],
            "citations": [],
        }

    monkeypatch.setattr("vietnam_legal_agent.agent.v4.run_workflow", fake_run_workflow)
    query = "Tôi bị công ty cho nghỉ việc đột ngột, quyền lợi của tôi thế nào?"
    state = await app.run(
        query=query,
        user_id="v4-user",
        conversation_id="labor-case",
        intent_hint="case_assessment",
    )

    assert state["outcome"] == "completed"
    assert state["route"] == "legal_lookup"
    assert state["task_type"] == "legal_lookup"
    assert observed["query"] == query
    assert observed["plan"]["route"] == "legal_lookup"
    assert observed["plan"]["task_type"] == "legal_lookup"
    assert "cho nghỉ việc đột ngột" in observed["plan"]["standalone_query"]
    assert observed["plan"]["legal_topics"] == ["labor"]
    assert state["rule_id"] == ""


@pytest.mark.asyncio
async def test_general_checklist_is_a_normal_cited_request(monkeypatch: pytest.MonkeyPatch):
    history = MemoryHistory()
    app, _retrieval = runtime(history)
    observed: dict[str, Any] = {}

    async def fake_run_workflow(query: str, **kwargs: Any):
        observed["plan"] = kwargs["precomputed_understanding"]
        return {
            "query": query,
            "user_id": kwargs["user_id"],
            "conversation_id": kwargs["conversation_id"],
            "trace_id": kwargs["trace_id"],
            "termination_reason": "answer_complete",
            "answer": "Các bước cần kiểm tra theo căn cứ đã truy xuất. [1]",
            "source": "legal",
            "evidence": [],
            "citations": [],
        }

    monkeypatch.setattr("vietnam_legal_agent.agent.v4.run_workflow", fake_run_workflow)
    state = await app.run(
        query="Tôi cần làm gì sau khi bị chủ nhà giữ tiền cọc?",
        user_id="v4-user",
        conversation_id="civil-checklist",
        intent_hint="compliance_checklist",
    )

    assert state["outcome"] == "completed"
    assert state["route"] == "legal_lookup"
    assert "danh sách các bước" in observed["plan"]["standalone_query"]
    assert observed["plan"]["legal_topics"] == ["civil_contract"]


@pytest.mark.asyncio
async def test_natural_case_description_uses_the_same_legal_lookup_path(monkeypatch: pytest.MonkeyPatch):
    history = MemoryHistory()
    app, _retrieval = runtime(history)
    observed: dict[str, Any] = {}

    async def fake_run_workflow(query: str, **kwargs: Any):
        observed["plan"] = kwargs["precomputed_understanding"]
        return {
            "query": query,
            "user_id": kwargs["user_id"],
            "conversation_id": kwargs["conversation_id"],
            "trace_id": kwargs["trace_id"],
            "termination_reason": "answer_complete",
            "answer": "Đã tra cứu căn cứ pháp lý phù hợp. [1]",
            "source": "legal",
            "evidence": [],
            "citations": [],
        }

    monkeypatch.setattr("vietnam_legal_agent.agent.v4.run_workflow", fake_run_workflow)
    state = await app.run(
        query="Công ty chậm trả lương của tôi trong hai tháng, tôi nên làm gì?",
        user_id="v4-user", conversation_id="ordinary-chat", intent_hint="case_assessment",
        interaction_source="composer",
    )
    assert state["route"] == "legal_lookup"
    assert state["task_type"] == "legal_lookup"
    assert state["rule_id"] == ""
    assert state["outcome"] == "completed"
    assert state["result_type"] == "legal_answer"
    assert "chậm trả lương" in observed["plan"]["standalone_query"]
