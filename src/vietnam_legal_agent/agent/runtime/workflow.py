"""SSE runtime for the bounded LangGraph workflow."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

from vietnam_legal_agent.agent.workflow.builder import build_workflow
from vietnam_legal_agent.agent.workflow.contracts import WorkflowDependencies
from vietnam_legal_agent.agent.workflow.execution import create_initial_state, run_workflow
from vietnam_legal_agent.domain.models import AgentState, TaskType, TerminationReason
from vietnam_legal_agent.domain.verification import VerificationStatus

logger = logging.getLogger(__name__)


from vietnam_legal_agent.agent.runtime.presentation import (
    _ACTION_STATUS,
    _documents_for_api,
    _metadata,
    _source_snapshots,
    split_verified_answer_for_stream,
)


class WorkflowRuntime:
    def __init__(
        self,
        deps: WorkflowDependencies,
        *,
        answer_chunk_size: int = 180,
        answer_chunk_delay_s: float = 0.015,
    ) -> None:
        self.deps = deps
        self.answer_chunk_size = answer_chunk_size
        self.answer_chunk_delay_s = max(answer_chunk_delay_s, 0.0)
        # LangGraph compilation is independent of a turn's user data. Cache it
        # per runtime so repeated messages do not rebuild the same graph.
        self._compiled_workflow = build_workflow(deps)

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
                TaskType.CASE_ASSESSMENT.value,
                TaskType.BUILD_COMPLIANCE_CHECKLIST.value,
            }:
                await self.deps.history.clear_case(user_id, conversation_id)
                state["case_state"] = {
                    **dict(state.get("case_state") or {}),
                    "status": "completed",
                    "missing_facts": [],
                }

            assistant_message_id = await self.deps.history.save_exchange(
                user_id,
                conversation_id,
                state["query"],
                answer,
                _metadata(state),
            )
            if assistant_message_id is not None:
                state["assistant_message_id"] = str(assistant_message_id)
            state["sources"] = _source_snapshots(state)

            # Only standalone legal answers from the corpus are reusable.  Case
            # assessments/checklists and web responses are deliberately excluded.
            cacheable = (
                state.get("task_type") == TaskType.LEGAL_LOOKUP.value
                and state.get("route") == "legal_lookup"
                and state.get("source") == "legal"
                and state.get("termination_reason") == TerminationReason.ANSWER_COMPLETE.value
                and bool(state.get("citation_valid"))
                and bool((state.get("evidence_assessment") or {}).get("sufficient"))
                and state.get("verification_status") == VerificationStatus.VERIFIED.value
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
                    route="legal_lookup",
                )
        except Exception as exc:  # noqa: BLE001 - persistence must not lose a verified response
            # Persistence failures should be observable but must not turn a
            # verified answer into a server error.
            logger.warning("Workflow persistence failed for trace=%s: %s", state.get("trace_id"), exc)
        finally:
            try:
                await self.deps.history.record_run(state, started_at, time.perf_counter())
                logger.info(
                    "%s",
                    json.dumps(
                        {
                            "event": "agent_run_completed",
                            "trace_id": state.get("trace_id"),
                            "conversation_id": state.get("conversation_id"),
                            "termination_reason": state.get("termination_reason"),
                            "actions": state.get("action_sequence"),
                            "duration_ms": state.get("run_duration_ms"),
                        },
                        ensure_ascii=False,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - trace persistence is best effort
                logger.warning("Workflow trace persistence failed: %s", exc)

    async def run(self, **kwargs: Any) -> AgentState:
        started_at = time.perf_counter()
        started_wall = datetime.now(UTC)
        state = await run_workflow(deps=self.deps, compiled_workflow=self._compiled_workflow, **kwargs)
        from vietnam_legal_agent.config import get_settings

        state["preview"] = get_settings().corpus_runtime_mode == "preview"
        state["run_started_at"] = started_wall.isoformat()
        state["run_ended_at"] = datetime.now(UTC).isoformat()
        state["run_duration_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
        await self._persist(state, started_at=started_at)
        return state

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "status", "message": "Đang nạp ngữ cảnh cuộc trò chuyện…", "stage": "load_context"}
        started_at = time.perf_counter()
        started_wall = datetime.now(UTC)
        trace_id = str(kwargs.get("trace_id") or "")
        pipeline_version = "pipeline-v4"
        try:
            state = await create_initial_state(deps=self.deps, **kwargs)
            from vietnam_legal_agent.config import get_settings

            state["preview"] = get_settings().corpus_runtime_mode == "preview"
            trace_id = state.get("trace_id", "")
            compiled = self._compiled_workflow
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
                chunks = split_verified_answer_for_stream(answer, max_chunk_chars=self.answer_chunk_size)
                yield {
                    "type": "status",
                    "message": "Đã xác minh trích dẫn. Đang hiển thị câu trả lời…",
                    "stage": "streaming",
                }
                for index, chunk in enumerate(chunks, start=1):
                    yield {
                        "type": "response_chunk",
                        "chunk": chunk,
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                        "stage": "streaming",
                    }
                    # Give the browser a chance to paint each chunk even when
                    # the server and client are on the same local machine.
                    if index < len(chunks) and self.answer_chunk_delay_s:
                        await asyncio.sleep(self.answer_chunk_delay_s)
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
                "code": "pipeline_error",
                "message": "Internal server error. Please try again.",
                "retryable": True,
                "retry_after_seconds": 2,
                "trace_id": trace_id,
                "pipeline_version": pipeline_version,
            }
