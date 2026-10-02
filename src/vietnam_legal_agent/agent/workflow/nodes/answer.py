"""LangGraph implementation of the bounded legal workflow."""

from __future__ import annotations

import logging

from vietnam_legal_agent.domain.models import (
    Action,
    AgentState,
    TaskType,
    TerminationReason,
    append_action,
    documents_from_dict,
)
from vietnam_legal_agent.tools.evidence import (
    propagate_list_item_citations,
)

logger = logging.getLogger(__name__)

from vietnam_legal_agent.agent.workflow.contracts import (
    _append_source_version_caveat,
    _trace,
)
from vietnam_legal_agent.agent.workflow.nodes.context import WorkflowNodeContext


class AnswerNodeHandlers(WorkflowNodeContext):
    async def compose_answer(self, state: AgentState) -> AgentState:
        append_action(state, Action.COMPOSE_ANSWER)
        task = TaskType(state["task_type"])
        docs = documents_from_dict(state.get("evidence"))
        if task == TaskType.CHITCHAT:
            answer = await self.deps.generation.chitchat(state["query"], state.get("history", []))
            state["source"] = "chitchat"
        elif state.get("source") == "web_search":
            answer = state.get("web_answer", "")
        else:
            answer = await self.deps.generation.answer(
                task.value, state["standalone_query"], docs, state.get("facts", {})
            )
            if (state.get("evidence_assessment") or {}).get("source_version_only"):
                answer = _append_source_version_caveat(answer)
            answer = propagate_list_item_citations(answer or "")
        state["answer"] = answer or ""
        state["assessment"] = None
        state["checklist"] = []
        state["case_state"] = None
        return state

    async def repair_answer(self, state: AgentState) -> AgentState:
        append_action(state, Action.REPAIR_ANSWER)
        state["repair_count"] = int(state.get("repair_count", 0)) + 1
        docs = documents_from_dict(state.get("evidence"))
        state["answer"] = await self.deps.generation.repair(
            state.get("answer", ""),
            docs,
            state["task_type"],
            query=str(state.get("standalone_query") or state.get("query") or ""),
        )
        if (state.get("evidence_assessment") or {}).get("source_version_only"):
            state["answer"] = _append_source_version_caveat(state["answer"])
        return state

    async def finish(self, state: AgentState) -> AgentState:
        append_action(state, Action.FINISH)
        if not state.get("termination_reason"):
            state["termination_reason"] = (
                TerminationReason.RESEARCH_COMPLETE.value
                if state.get("source") == "web_search"
                else TerminationReason.ANSWER_COMPLETE.value
            )
        state["evidence_status"] = state.get("evidence_status") or "sufficient"
        _trace(state, reason_code=state["termination_reason"])
        return state
