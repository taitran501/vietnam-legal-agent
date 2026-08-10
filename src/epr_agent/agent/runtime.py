"""Streaming presenter for the bounded workflow."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, cast

from epr_agent.agent.graph import (
    WorkflowDependencies,
    build_workflow,
    create_initial_state,
    default_dependencies,
    run_workflow,
)
from epr_agent.domain.models import AgentState, TaskType, TerminationReason

logger = logging.getLogger(__name__)

_ACTION_STATUS = {
    "load_context": "Đã nạp lịch sử và trạng thái tình huống.",
    "understand_task": "Đã hiểu yêu cầu và kiểm tra thông tin đầu vào.",
    "check_cache": "Đã kiểm tra câu trả lời có thể tái sử dụng.",
    "answer_cache": "Đã xác minh câu trả lời từ bộ nhớ đệm.",
    "ask_user": "Cần thêm thông tin trước khi tiếp tục.",
    "retrieve_legal": "Đã truy xuất tài liệu pháp luật.",
    "evaluate_evidence": "Đã đánh giá mức độ đầy đủ của bằng chứng.",
    "retrieve_web": "Đã kiểm tra nguồn web trong phạm vi EPR.",
    "compose_answer": "Đã soạn câu trả lời dựa trên bằng chứng.",
    "verify_citations": "Đã kiểm tra trích dẫn và điều luật.",
    "repair_answer": "Đã sửa câu trả lời theo nguồn đã truy xuất.",
    "finish": "Workflow đã hoàn tất.",
    "safe_stop": "Workflow đã dừng an toàn.",
}


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
        "case_state": state.get("case_state"),
        "assessment": state.get("assessment"),
        "checklist": checklist,
        "assumptions": assumptions,
        "missing_facts": state.get("missing_facts", []),
        "citations": state.get("citations", []),
        "evidence_assessment": state.get("evidence_assessment", {}),
        "trace_id": state.get("trace_id", ""),
        "corpus_id": state.get("corpus_id", "epr"),
        "pipeline_version": state.get("pipeline_version", "legal-first-v2"),
        "termination_reason": state.get("termination_reason", TerminationReason.ERROR.value),
    }


class WorkflowRuntime:
    def __init__(self, deps: WorkflowDependencies) -> None:
        self.deps = deps

    async def _persist(self, state: AgentState, *, started_at: float) -> None:
        user_id = state["user_id"]
        conversation_id = state["conversation_id"]
        answer = state.get("answer", "")
        try:
            active_case = state.get("active_case")
            if state.get("awaiting_user_input") and active_case:
                saved_case = await self.deps.history.save_case(user_id, conversation_id, active_case)
                if saved_case is not None:
                    state["case_state"] = saved_case
            elif state.get("task_type") in {
                TaskType.ASSESS_EPR_OBLIGATION.value,
                TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
            }:
                await self.deps.history.clear_case(user_id, conversation_id)
                state["case_state"] = {
                    **dict(state.get("case_state") or {}),
                    "status": "completed",
                    "missing_facts": [],
                }

            await self.deps.history.save_exchange(
                user_id,
                conversation_id,
                state["query"],
                answer,
                _metadata(state),
            )

            # Only standalone legal answers from the corpus are reusable.  Case
            # assessments/checklists and web responses are deliberately excluded.
            cacheable = (
                state.get("task_type") == TaskType.LEGAL_LOOKUP.value
                and state.get("source") == "legal"
                and state.get("termination_reason") == TerminationReason.ANSWER_COMPLETE.value
                and bool(state.get("citation_valid"))
                and bool((state.get("evidence_assessment") or {}).get("sufficient"))
            )
            state["cache_status"] = "stored" if cacheable else "not_cacheable"
            if cacheable:
                await self.deps.cache.store(
                    TaskType.LEGAL_LOOKUP,
                    state.get("standalone_query", state["query"]),
                    answer,
                    evidence=list(state.get("evidence") or []),
                    citations=list(state.get("citations") or []),
                    source=str(state.get("source") or ""),
                )
        except Exception as exc:  # noqa: BLE001 - persistence must not lose a verified response
            # Persistence failures should be observable but must not turn a
            # verified answer into a server error.
            logger.warning("Workflow persistence failed for trace=%s: %s", state.get("trace_id"), exc)
        finally:
            try:
                await self.deps.history.record_run(state, started_at, time.perf_counter())
                logger.info("%s", json.dumps({
                    "event": "agent_run_completed",
                    "trace_id": state.get("trace_id"),
                    "conversation_id": state.get("conversation_id"),
                    "termination_reason": state.get("termination_reason"),
                    "actions": state.get("action_sequence"),
                    "duration_ms": state.get("run_duration_ms"),
                }, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001 - trace persistence is best effort
                logger.warning("Workflow trace persistence failed: %s", exc)

    async def run(self, **kwargs: Any) -> AgentState:
        started_at = time.perf_counter()
        started_wall = datetime.now(UTC)
        state = await run_workflow(deps=self.deps, **kwargs)
        state["run_started_at"] = started_wall.isoformat()
        state["run_ended_at"] = datetime.now(UTC).isoformat()
        state["run_duration_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
        await self._persist(state, started_at=started_at)
        return state

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "status", "message": "Đang nạp ngữ cảnh cuộc trò chuyện…", "stage": "load_context"}
        started_at = time.perf_counter()
        started_wall = datetime.now(UTC)
        try:
            state = await create_initial_state(deps=self.deps, **kwargs)
            trace_id = state.get("trace_id", "")
            compiled = build_workflow(self.deps)
            step = 0
            async for update in compiled.astream(state, stream_mode="updates"):
                for node_state in update.values():
                    if not isinstance(node_state, dict):
                        continue
                    state.update(cast(AgentState, node_state))
                    action = str(node_state.get("current_action") or "")
                    if not action:
                        continue
                    step += 1
                    yield {
                        "type": "workflow_step",
                        "step": step,
                        "action": action,
                        "status": "completed",
                        "trace_id": trace_id,
                    }
                    yield {
                        "type": "status",
                        "message": _ACTION_STATUS.get(action, "Đã hoàn tất một bước xử lý."),
                        "stage": action,
                    }

            state["run_started_at"] = started_wall.isoformat()
            state["run_ended_at"] = datetime.now(UTC).isoformat()
            state["run_duration_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
            await self._persist(state, started_at=started_at)
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
    runtime: WorkflowRuntime | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Public SSE event generator used by the compatibility API route."""

    selected = runtime or get_default_runtime()
    async for event in selected.stream(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        legacy_session_id=legacy_session_id,
    ):
        yield event
