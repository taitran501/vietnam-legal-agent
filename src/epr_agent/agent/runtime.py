"""Streaming presenter for the bounded workflow."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from epr_agent.agent.graph import WorkflowDependencies, default_dependencies, run_workflow
from epr_agent.domain.models import AgentState, TaskType, TerminationReason

logger = logging.getLogger(__name__)


def _documents_for_api(state: AgentState) -> list[dict[str, Any]]:
    return [
        {
            "page_content": item.get("content", ""),
            "metadata": item.get("metadata", {}),
            "document_id": item.get("document_id", ""),
            "score": item.get("score"),
            "source": item.get("source", ""),
        }
        for item in state.get("evidence", [])
    ]


def _metadata(state: AgentState) -> dict[str, Any]:
    checklist = state.get("checklist", [])
    assumptions = [item.get("assumption") for item in checklist if item.get("assumption")]
    if state.get("assessment"):
        assumptions.append("Kết quả đánh giá là sơ bộ và phụ thuộc vào các facts đã cung cấp.")
    return {
        "task_type": state.get("task_type", TaskType.LEGAL_LOOKUP.value),
        "assessment": state.get("assessment"),
        "checklist": checklist,
        "assumptions": assumptions,
        "missing_facts": state.get("missing_facts", []),
        "citations": state.get("citations", []),
        "trace_id": state.get("trace_id", ""),
        "termination_reason": state.get("termination_reason", TerminationReason.ERROR.value),
    }


class WorkflowRuntime:
    def __init__(self, deps: WorkflowDependencies) -> None:
        self.deps = deps

    async def _persist(self, state: AgentState, *, started_at: float) -> None:
        user_id = state["user_id"]
        conversation_id = state["conversation_id"]
        answer = state.get("answer", "")
        metadata = _metadata(state)
        try:
            await self.deps.history.save_exchange(
                user_id,
                conversation_id,
                state["query"],
                answer,
                metadata,
            )
            if state.get("awaiting_user_input") and state.get("active_case"):
                await self.deps.history.save_case(user_id, conversation_id, state["active_case"])
            elif state.get("task_type") in {
                TaskType.ASSESS_EPR_OBLIGATION.value,
                TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
            }:
                await self.deps.history.clear_case(user_id, conversation_id)

            # Only standalone legal answers from the corpus are reusable.  Case
            # assessments/checklists and web responses are deliberately excluded.
            if (
                state.get("task_type") == TaskType.LEGAL_LOOKUP.value
                and state.get("source") in {"faq", "legal"}
                and state.get("termination_reason") == TerminationReason.ANSWER_COMPLETE.value
            ):
                await self.deps.cache.store(
                    TaskType.LEGAL_LOOKUP,
                    state.get("standalone_query", state["query"]),
                    answer,
                )
        except Exception as exc:  # noqa: BLE001 - persistence must not lose a verified response
            # Persistence failures should be observable but must not turn a
            # verified answer into a server error.
            logger.warning("Workflow persistence failed for trace=%s: %s", state.get("trace_id"), exc)
        finally:
            try:
                await self.deps.history.record_run(state, started_at, time.perf_counter())
            except Exception as exc:  # noqa: BLE001 - trace persistence is best effort
                logger.warning("Workflow trace persistence failed: %s", exc)

    async def run(self, **kwargs: Any) -> AgentState:
        started_at = time.perf_counter()
        state = await run_workflow(deps=self.deps, **kwargs)
        await self._persist(state, started_at=started_at)
        return state

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "status", "message": "Đang nạp ngữ cảnh cuộc trò chuyện…", "stage": "load_context"}
        try:
            state = await self.run(**kwargs)
            trace_id = state.get("trace_id", "")
            for index, action in enumerate(state.get("action_sequence", []), start=1):
                yield {
                    "type": "workflow_step",
                    "step": index,
                    "action": action,
                    "status": "completed",
                    "trace_id": trace_id,
                }
            yield {
                "type": "status",
                "message": "Đã hoàn tất kiểm tra nguồn và tạo câu trả lời.",
                "stage": "complete",
            }
            answer = state.get("answer", "")
            if answer:
                yield {"type": "response_chunk", "chunk": answer, "stage": "streaming"}
            yield {
                "type": "response_complete",
                "text": answer,
                "documents": _documents_for_api(state),
                "source": state.get("source", "error"),
                "stage": "complete",
                **_metadata(state),
            }
        except Exception:
            logger.exception("Bounded workflow failed")
            yield {
                "type": "error",
                "message": "Internal server error. Please try again.",
            }


@lru_cache(maxsize=1)
def get_default_runtime() -> WorkflowRuntime:
    return WorkflowRuntime(default_dependencies())


async def stream_chat(
    *,
    query: str,
    user_id: str,
    conversation_id: str,
    legacy_session_id: str = "",
    faq_threshold: float = 0.75,
    runtime: WorkflowRuntime | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Public SSE event generator used by the compatibility API route."""

    selected = runtime or get_default_runtime()
    async for event in selected.stream(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        legacy_session_id=legacy_session_id,
        faq_threshold=faq_threshold,
    ):
        yield event
