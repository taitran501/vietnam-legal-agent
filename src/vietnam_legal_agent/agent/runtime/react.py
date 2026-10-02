"""SSE runtime for the autonomous legal-agent loop."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from vietnam_legal_agent.agent.workflow.contracts import (
    WorkflowDependencies,
    _verification_status_for_reason,
)
from vietnam_legal_agent.domain.models import AgentState, DocumentRecord, TerminationReason
from vietnam_legal_agent.domain.routes import RouteType, route_spec
from vietnam_legal_agent.domain.verification import VerificationPolicy

logger = logging.getLogger(__name__)


from vietnam_legal_agent.agent.runtime.presentation import (
    _documents_for_api,
    _metadata,
    split_verified_answer_for_stream,
)


@dataclass(slots=True)
class _AgentTurnLifecycle:
    """Own one pipeline-agent durable turn across every stream exit path."""

    history: Any
    user_id: str
    conversation_id: str
    turn_id: str
    mode: str
    operation: str
    replay_metadata: dict[str, Any] = field(default_factory=dict)
    target_assistant_message_id: Any = None
    trace_id: str = ""
    started: bool = False
    finalized: bool = False

    @property
    def durable(self) -> bool:
        return (
            bool(self.turn_id)
            and callable(getattr(self.history, "begin_turn", None))
            and callable(getattr(self.history, "finish_turn", None))
        )

    async def begin(self, query: str) -> dict[str, Any] | None:
        if not self.durable:
            return None
        handle = await self.history.begin_turn(
            self.user_id,
            self.conversation_id,
            self.turn_id,
            query,
            mode=self.mode,
            operation=self.operation,
            replay_metadata=self.replay_metadata,
            target_assistant_message_id=self.target_assistant_message_id,
        )
        if not isinstance(handle, dict):
            return None
        self.started = True
        return handle

    async def is_cancelled(self) -> bool:
        checker = getattr(self.history, "is_turn_cancelled", None)
        if not self.started or not callable(checker):
            return False
        return bool(await checker(self.user_id, self.conversation_id, self.turn_id))

    async def finish(
        self,
        *,
        content: str,
        status: str,
        metadata: dict[str, Any],
        error_code: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.started or self.finalized:
            return None
        final = await self.history.finish_turn(
            self.user_id,
            self.conversation_id,
            self.turn_id,
            content=content,
            metadata=metadata,
            status=status,
            error_code=error_code,
        )
        if not isinstance(final, dict):
            raise PermissionError("durable turn is not owned by current user")
        self.finalized = True
        return final

    async def finish_interrupted(self, *, status: str, error_code: str) -> None:
        if not self.started or self.finalized:
            return
        await self.finish(
            content="",
            status=status,
            metadata={
                "turn_status": status,
                "trace_id": self.trace_id,
                "pipeline_version": "pipeline-agent",
                "replay_metadata": self.replay_metadata,
            },
            error_code=error_code,
        )


class AgentWorkflowRuntime:
    """Autonomous Agent runtime implementing the standard SSE streaming contract."""

    def __init__(
        self,
        deps: WorkflowDependencies,
        *,
        runner: Any | None = None,
        guardrails: Any | None = None,
        answer_chunk_size: int = 180,
        answer_chunk_delay_s: float = 0.015,
    ) -> None:
        self.deps = deps
        self.answer_chunk_size = answer_chunk_size
        self.answer_chunk_delay_s = max(answer_chunk_delay_s, 0.0)

        from vietnam_legal_agent.agent.guardrails import AgentGuardrails

        self._guardrails = guardrails or AgentGuardrails()
        self._runner = runner

    @property
    def runner(self) -> Any:
        if self._runner is None:
            from vietnam_legal_agent.agent.agent_loop import AgentRunConfig, VietnameseLegalAgentRunner

            self._runner = VietnameseLegalAgentRunner(
                config=AgentRunConfig(max_steps=5, max_search_calls=4, max_web_calls=1)
            )
        return self._runner

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        trace_id = str(kwargs.get("trace_id") or uuid.uuid4())
        request_kwargs = {**kwargs, "trace_id": trace_id}
        lifecycle = _AgentTurnLifecycle(
            history=self.deps.history,
            user_id=str(kwargs.get("user_id") or ""),
            conversation_id=str(kwargs.get("conversation_id") or ""),
            turn_id=str(kwargs.get("turn_id") or trace_id),
            mode=str(kwargs.get("mode") or "auto"),
            operation=str(kwargs.get("operation") or "message"),
            replay_metadata=dict(kwargs.get("replay_metadata") or {}),
            target_assistant_message_id=kwargs.get("target_assistant_message_id"),
            trace_id=trace_id,
        )
        fallback_status = "stopped"
        fallback_error_code = "client_disconnected"
        try:
            async for event in self._stream(lifecycle=lifecycle, **request_kwargs):
                yield event
        except asyncio.CancelledError:
            try:
                await lifecycle.finish_interrupted(status="stopped", error_code="client_disconnected")
            except Exception:
                logger.exception("Failed to finalize cancelled agent stream", extra={"trace_id": trace_id})
            raise
        except Exception:
            fallback_status = "failed"
            fallback_error_code = "stream_incomplete"
            try:
                await lifecycle.finish_interrupted(status=fallback_status, error_code=fallback_error_code)
            except Exception:
                logger.exception("Failed to finalize failed agent stream", extra={"trace_id": trace_id})
            raise
        finally:
            if lifecycle.started and not lifecycle.finalized:
                try:
                    await lifecycle.finish_interrupted(status=fallback_status, error_code=fallback_error_code)
                except Exception:
                    logger.exception("Failed to finalize interrupted agent stream", extra={"trace_id": trace_id})

    async def _stream(self, *, lifecycle: _AgentTurnLifecycle, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        query = str(kwargs.get("query") or "").strip()
        user_id = str(kwargs.get("user_id") or "")
        conversation_id = str(kwargs.get("conversation_id") or "")
        trace_id = str(kwargs.get("trace_id") or uuid.uuid4())
        mode = str(kwargs.get("mode") or "auto")
        started_at = time.perf_counter()
        started_wall = datetime.now(UTC)

        operation = str(kwargs.get("operation") or "message")

        from vietnam_legal_agent.config import get_settings
        from vietnam_legal_agent.tracing.trace_context import get_trace_store

        preview = get_settings().corpus_runtime_mode == "preview"
        legal_readiness_status = ""
        legal_readiness_sha = ""

        # ── 1. Context Loading & Query Recovery for Replays ──
        snapshot = await self.deps.history.load(user_id, conversation_id, max_messages=6)
        if not query and operation in {"retry", "regenerate"}:
            for msg in reversed(snapshot.history):
                if msg.get("role") == "user" and str(msg.get("content") or "").strip():
                    query = str(msg["content"]).strip()
                    break

        from vietnam_legal_agent.domain.tasks import (
            deterministic_task_understanding,
            is_context_dependent_query,
            latest_turn_requires_context,
        )

        # Resolve terse follow-ups before the autonomous loop using LLM structured understanding
        if self.deps.understanding is not None:
            try:
                understanding = await self.deps.understanding.understand(
                    query,
                    snapshot.history,
                    summary="",
                    active_case=snapshot.active_case,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Structured task understanding failed: %s; falling back", exc)
                understanding = deterministic_task_understanding(
                    query,
                    snapshot.history,
                    snapshot.active_case,
                )
        else:
            understanding = deterministic_task_understanding(
                query,
                snapshot.history,
                snapshot.active_case,
            )
        standalone_query = understanding.standalone_query or query
        retrieval_queries = list(understanding.retrieval_queries or [])
        is_follow_up = bool(understanding.is_follow_up)
        context_dependent_follow_up = is_context_dependent_query(query)
        if context_dependent_follow_up and snapshot.history:
            # The structured model may describe a short continuation as a
            # standalone question. Preserve the observable context state from
            # the actual user message so downstream handling cannot lose it.
            is_follow_up = True
        context_loaded = True
        history_messages = len(snapshot.history)

        trace_session = get_trace_store().create_trace(
            trace_id=trace_id,
            conversation_id=conversation_id,
            user_id=user_id,
            query=query,
        )
        context_span = trace_session.start_span("load_context")
        context_span.close(
            status="ok",
            extra_attrs={
                "history_messages": history_messages,
                "context_loaded": context_loaded,
                "is_follow_up": is_follow_up,
                "standalone_query_length": len(standalone_query),
            },
        )

        try:
            await lifecycle.begin(query)
        except Exception as exc:  # noqa: BLE001 - storage is a required agent dependency
            logger.warning("Agent turn initialization failed: %s", exc)
            trace_session.finish(metadata={"error": "storage_unavailable"})
            yield {
                "type": "error",
                "code": "storage_unavailable",
                "message": "Không thể lưu lượt xử lý. Vui lòng thử lại.",
                "retryable": True,
                "retry_after_seconds": 2,
                "trace_id": trace_id,
                "pipeline_version": "pipeline-agent",
            }
            return

        yield {
            "type": "status",
            "message": "Đã nạp lịch sử và kiểm tra ngữ cảnh hội thoại.",
            "stage": "load_context",
            "context_loaded": context_loaded,
            "history_messages": history_messages,
            "is_follow_up": is_follow_up,
            "standalone_query": standalone_query,
            "trace_id": trace_id,
            "pipeline_version": "pipeline-agent",
        }

        def storage_error_event(message: str) -> dict[str, Any]:
            return {
                "type": "error",
                "code": "storage_unavailable",
                "message": message,
                "retryable": True,
                "retry_after_seconds": 2,
                "trace_id": trace_id,
                "pipeline_version": "pipeline-agent",
            }

        def stopped_event() -> dict[str, Any]:
            return {
                "type": "response_stopped",
                "text": "",
                "turn_status": "stopped",
                "termination_reason": "user_cancelled",
                "trace_id": trace_id,
                "pipeline_version": "pipeline-agent",
            }

        async def finish_fast_path(
            answer: str,
            *,
            source: str,
            termination_reason: str,
            save_legacy_exchange: bool,
        ) -> dict[str, Any] | None:
            metadata = {
                "pipeline_version": "pipeline-agent",
                "source": source,
                "termination_reason": termination_reason,
                "trace_id": trace_id,
                "context_loaded": context_loaded,
                "history_messages": history_messages,
                "is_follow_up": is_follow_up,
                "standalone_query": standalone_query,
                "replay_metadata": lifecycle.replay_metadata,
                "legal_readiness_status": legal_readiness_status,
                "legal_readiness_sha": legal_readiness_sha,
            }
            if lifecycle.started:
                if await lifecycle.is_cancelled():
                    return await lifecycle.finish(
                        content="",
                        status="stopped",
                        metadata={**metadata, "turn_status": "stopped"},
                        error_code="user_cancelled",
                    )
                final = await lifecycle.finish(
                    content=answer,
                    status="complete",
                    metadata={**metadata, "turn_status": "complete"},
                )
                if str((final or {}).get("status") or "failed") not in {"complete", "stopped"}:
                    raise RuntimeError("durable fast-path finalization did not complete")
                return final
            if save_legacy_exchange:
                await self.deps.history.save_exchange(user_id, conversation_id, query, answer, metadata)
            return None

        try:
            if await lifecycle.is_cancelled():
                await lifecycle.finish(
                    content="",
                    status="stopped",
                    metadata={
                        "turn_status": "stopped",
                        "trace_id": trace_id,
                        "pipeline_version": "pipeline-agent",
                        "replay_metadata": lifecycle.replay_metadata,
                    },
                    error_code="user_cancelled",
                )
                trace_session.finish(metadata={"termination": "user_cancelled"})
                yield stopped_event()
                return
        except Exception as exc:  # noqa: BLE001 - cancellation state is durable storage
            logger.warning("Agent cancellation check failed: %s", exc)
            trace_session.finish(metadata={"error": "storage_unavailable"})
            yield storage_error_event("Không thể kiểm tra trạng thái lượt xử lý. Vui lòng thử lại.")
            return

        # ── 2. Input Validation Guardrail ──
        s_val = trace_session.start_span("validate_input")
        yield {"type": "status", "message": "Đang kiểm tra câu hỏi…", "stage": "validate_input"}
        is_valid, _input_reason = self._guardrails.check_input(query)
        s_val.close(status="ok" if is_valid else "invalid")
        if not is_valid:
            safe_msg = "Câu hỏi cần có nội dung và không vượt quá 3.000 ký tự. Bạn hãy gửi lại câu hỏi ngắn gọn hơn."
            try:
                final = await finish_fast_path(
                    safe_msg,
                    source="error",
                    termination_reason=TerminationReason.INVALID_INPUT.value,
                    save_legacy_exchange=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Agent fast-path persistence failed: %s", exc)
                trace_session.finish(metadata={"error": "storage_unavailable"})
                yield storage_error_event("Không thể lưu kết quả. Vui lòng thử lại.")
                return
            if final and final.get("status") == "stopped":
                yield stopped_event()
                return
            trace_session.finish(metadata={"termination": TerminationReason.INVALID_INPUT.value})
            yield {
                "type": "response_complete",
                "text": safe_msg,
                "documents": [],
                "source": "error",
                "stage": "complete",
                "pipeline_version": "pipeline-agent",
                "termination_reason": TerminationReason.INVALID_INPUT.value,
                "trace_id": trace_id,
            }
            return

        # Do not let an elliptical follow-up turn an unresolved response into
        # a fresh retrieval with a guessed topic. Ask for the missing subject
        # in a new conversation and after a prior answer explicitly requested
        # clarification or stopped for insufficient evidence.
        if (
            context_dependent_follow_up
            and not snapshot.active_case
            and (not snapshot.history or latest_turn_requires_context(snapshot.history))
        ):
            clarification = (
                "Câu hỏi tiếp theo chưa cho biết rõ nội dung cần tra cứu. "
                "Bạn hãy nêu tên văn bản, lĩnh vực hoặc vấn đề cụ thể để tôi kiểm tra căn cứ pháp lý phù hợp."
            )
            if latest_turn_requires_context(snapshot.history):
                clarification = (
                    "Lượt trước chưa có đủ căn cứ phù hợp để kết luận, nên câu hỏi tiếp theo chưa xác định rõ nội dung cần tra cứu. "
                    "Bạn hãy nêu tên văn bản, lĩnh vực hoặc vấn đề cụ thể để tôi tra cứu lại."
                )
            try:
                final = await finish_fast_path(
                    clarification,
                    source="follow_up",
                    termination_reason=TerminationReason.AWAITING_USER_INPUT.value,
                    save_legacy_exchange=True,
                )
            except Exception as exc:  # noqa: BLE001 - durable clarification is required
                logger.warning("Agent clarification persistence failed: %s", exc)
                trace_session.finish(metadata={"error": "storage_unavailable"})
                yield storage_error_event("Không thể lưu yêu cầu làm rõ. Vui lòng thử lại.")
                return
            if final and final.get("status") == "stopped":
                yield stopped_event()
                return
            trace_session.finish(
                metadata={
                    "source": "follow_up",
                    "termination": TerminationReason.AWAITING_USER_INPUT.value,
                    "context_loaded": context_loaded,
                    "history_messages": history_messages,
                    "is_follow_up": is_follow_up,
                    "steps_count": 0,
                }
            )
            yield {
                "type": "response_complete",
                "text": clarification,
                "documents": [],
                "source": "follow_up",
                "stage": "complete",
                "pipeline_version": "pipeline-agent",
                "termination_reason": TerminationReason.AWAITING_USER_INPUT.value,
                "awaiting_user_input": True,
                "context_loaded": context_loaded,
                "history_messages": history_messages,
                "is_follow_up": is_follow_up,
                "standalone_query": standalone_query,
                "trace_id": trace_id,
            }
            return

        # ── 3. Fast Bypass for Chitchat & Out of Scope ──
        # Route the user's actual turn; the rewritten query is only a bounded
        # retrieval/agent context and must not let quoted history change scope.
        route = (
            RouteType.RESEARCH_WEB
            if mode == RouteType.RESEARCH_WEB.value
            else (
                understanding.route
                if isinstance(understanding.route, RouteType)
                else RouteType(str(understanding.route))
            )
        )
        route_policy = route_spec(route).verification_policy
        if route.value == "chitchat":
            yield {"type": "status", "message": "Đang soạn câu trả lời…", "stage": "compose"}
            answer = await self.deps.generation.chitchat(query, snapshot.history)
            chunks = split_verified_answer_for_stream(answer, max_chunk_chars=self.answer_chunk_size)
            for idx, chunk in enumerate(chunks, start=1):
                yield {
                    "type": "response_chunk",
                    "chunk": chunk,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "stage": "streaming",
                }
            try:
                final = await finish_fast_path(
                    answer,
                    source="chitchat",
                    termination_reason=TerminationReason.ANSWER_COMPLETE.value,
                    save_legacy_exchange=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Agent chitchat persistence failed: %s", exc)
                trace_session.finish(metadata={"error": "storage_unavailable"})
                yield storage_error_event("Không thể lưu kết quả. Vui lòng thử lại.")
                return
            if final and final.get("status") == "stopped":
                yield stopped_event()
                return
            yield {
                "type": "response_complete",
                "text": answer,
                "documents": [],
                "source": "chitchat",
                "stage": "complete",
                "pipeline_version": "pipeline-agent",
                "termination_reason": TerminationReason.ANSWER_COMPLETE.value,
                "trace_id": trace_id,
            }
            return

        if route.value == "out_of_scope":
            safe_msg = "Câu hỏi hiện nằm ngoài phạm vi tra cứu pháp luật của hệ thống."
            try:
                final = await finish_fast_path(
                    safe_msg,
                    source="error",
                    termination_reason=TerminationReason.OUT_OF_SCOPE.value,
                    save_legacy_exchange=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Agent out-of-scope persistence failed: %s", exc)
                trace_session.finish(metadata={"error": "storage_unavailable"})
                yield storage_error_event("Không thể lưu kết quả. Vui lòng thử lại.")
                return
            if final and final.get("status") == "stopped":
                yield stopped_event()
                return
            yield {
                "type": "response_complete",
                "text": safe_msg,
                "documents": [],
                "source": "error",
                "stage": "complete",
                "pipeline_version": "pipeline-agent",
                "termination_reason": TerminationReason.OUT_OF_SCOPE.value,
                "trace_id": trace_id,
            }
            return

        # ── 4. Autonomous Agent Cognitive Loop ──
        turn_id = str(kwargs.get("turn_id") or trace_id)
        replay_metadata = dict(kwargs.get("replay_metadata") or {})

        async def turn_cancelled() -> bool:
            return await lifecycle.is_cancelled()

        async def finish_durable_turn(
            *, content: str, status: str, metadata: dict[str, Any], error_code: str | None = None
        ) -> dict[str, Any] | None:
            return await lifecycle.finish(content=content, status=status, metadata=metadata, error_code=error_code)

        _tool_status_messages = {
            "search_legal_provisions": "Đang tra cứu kho văn bản pháp luật…",
            "search_web_official": "Đang tìm kiếm thông tin từ cổng chính thức…",
            "lookup_answer_cache": "Đang kiểm tra bộ nhớ đệm câu trả lời…",
            "evaluate_legal_case": "Đang đối chiếu quy định và đánh giá tình huống…",
            "load_conversation_context": "Đang nạp ngữ cảnh hội thoại…",
            "ask_user_for_clarification": "Đang soạn câu hỏi làm rõ thông tin…",
        }

        s_loop = trace_session.start_span("agent_cognitive_loop")
        result = None
        current_tool_args: dict[str, Any] = {}
        pass_result = None
        requires_legal_evidence = route_spec(route).verification_policy is VerificationPolicy.LEGAL_CORPUS

        async def run_agent_pass(
            agent_query: str,
            *,
            search_query_hints: list[str] | None = None,
            max_steps: int | None = None,
        ) -> AsyncIterator[dict[str, Any]]:
            nonlocal current_tool_args, pass_result
            pass_result = None
            async for event in self.runner.stream(
                agent_query,
                history=snapshot.history,
                active_case=snapshot.active_case,
                history_summary=snapshot.summary,
                mode=mode,
                trace_id=trace_id,
                require_legal_evidence=requires_legal_evidence,
                retrieval_queries=search_query_hints,
                search_user_query=standalone_query,
                is_cancelled=turn_cancelled,
                max_steps=max_steps,
            ):
                if event.get("type") == "agent_tool_call":
                    tool_name = event.get("tool", "")
                    current_tool_args = event.get("args") or {}
                    status_message = _tool_status_messages.get(tool_name, "Đang xử lý bước tiếp theo…")
                    yield {
                        "type": "status",
                        "message": status_message,
                        "stage": tool_name,
                    }
                elif event.get("type") == "agent_tool_result":
                    tool_name = str(event.get("tool") or "")
                    tool_status = str(event.get("status") or "failed")
                    s_tool = trace_session.start_span(f"tool:{tool_name}")
                    s_tool.close(
                        status="ok" if tool_status == "completed" else tool_status,
                        extra_attrs={
                            "step": event.get("step", 1),
                            "latency_ms": event.get("latency_ms", 0.0),
                            "error_code": event.get("error_code"),
                        },
                    )
                    yield {
                        "type": "workflow_step",
                        "step": event.get("step", 1),
                        "action": tool_name,
                        "status": tool_status,
                        "label": _tool_status_messages.get(tool_name, "Đã hoàn thành bước."),
                        "latency_ms": event.get("latency_ms", 0.0),
                        "error_code": event.get("error_code"),
                        "args": current_tool_args,
                        "trace_id": trace_id,
                    }
                    current_tool_args = {}
                elif event.get("type") == "agent_complete":
                    pass_result = event.get("result")

        async for update in run_agent_pass(
            standalone_query,
            search_query_hints=retrieval_queries,
        ):
            yield update
        result = pass_result

        s_loop.close(
            model="gpt-4o-mini",
            input_tokens=len(query) * 2,
            output_tokens=len(result.answer if result else "") // 3,
            extra_attrs={"steps_taken": result.steps_taken if result else 0},
        )

        if result is None:
            try:
                await finish_durable_turn(
                    content="",
                    status="failed",
                    metadata={
                        "turn_status": "failed",
                        "trace_id": trace_id,
                        "pipeline_version": "pipeline-agent",
                    },
                    error_code="agent_error",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Agent error finalization failed: %s", exc)
                trace_session.finish(metadata={"error": "storage_unavailable"})
                yield storage_error_event("Không thể lưu trạng thái lỗi. Vui lòng thử lại.")
                return
            trace_session.finish(metadata={"error": "agent_error"})
            yield {
                "type": "error",
                "code": "agent_error",
                "message": "Không nhận được phản hồi từ agent.",
                "retryable": True,
                "trace_id": trace_id,
                "pipeline_version": "pipeline-agent",
            }
            return

        result.context_loaded = context_loaded
        result.history_messages = history_messages
        result.is_follow_up = is_follow_up
        result.standalone_query = standalone_query

        if result.termination_reason == "user_cancelled" or await turn_cancelled():
            stopped_metadata = {
                "turn_status": "stopped",
                "trace_id": trace_id,
                "pipeline_version": "pipeline-agent",
                "replay_metadata": replay_metadata,
            }
            try:
                await finish_durable_turn(
                    content="", status="stopped", metadata=stopped_metadata, error_code="user_cancelled"
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Agent cancellation persistence failed: %s", exc)
                trace_session.finish(metadata={"error": "storage_unavailable"})
                yield storage_error_event("Không thể lưu trạng thái dừng. Vui lòng thử lại.")
                return
            trace_session.finish(metadata={"termination": "user_cancelled"})
            yield stopped_event()
            return

        # ── 5. Output Verification Guardrail ──
        final_answer = result.answer
        termination_reason = result.termination_reason
        citations = list(result.citations)
        source = result.source
        evidence = list(result.evidence)
        verification_error = ""
        verification_status = ""

        route_policy = route_spec(route).verification_policy
        if termination_reason in {
            TerminationReason.ANSWER_COMPLETE.value,
            TerminationReason.CACHE_HIT.value,
            TerminationReason.RESEARCH_COMPLETE.value,
            TerminationReason.INSUFFICIENT_EVIDENCE.value,
        } and (
            source not in {"error", "follow_up"}
            or (
                requires_legal_evidence
                and evidence
                and termination_reason == TerminationReason.INSUFFICIENT_EVIDENCE.value
            )
        ):
            s_ver = trace_session.start_span("critic_and_citation_verification")
            yield {
                "type": "status",
                "message": "Đang xác minh căn cứ pháp lý và thẩm định phản biện…",
                "stage": "verify",
            }
            readiness_reason = ""
            if requires_legal_evidence and self.deps.legal_readiness is not None:
                try:
                    readiness = self.deps.legal_readiness.audit()
                    legal_readiness_status = readiness.status.value
                    legal_readiness_sha = readiness.manifest_sha256
                    allowed, gate_reason = self.deps.legal_readiness.allows_documents(
                        [DocumentRecord.from_dict(document) for document in evidence]
                    )
                    if not allowed:
                        readiness_reason = gate_reason or readiness.reason
                except Exception:  # noqa: BLE001 - an unreadable gate is a safe stop
                    readiness_reason = "legal_readiness_invalid"
                    legal_readiness_status = "invalid"
                    legal_readiness_sha = self.deps.legal_readiness.manifest_sha256
            if readiness_reason:
                passed, _reason, verified_or_fallback, checked_citations = (
                    False,
                    readiness_reason,
                    "Tôi chưa thể phát hành câu trả lời vì trạng thái pháp lý của nguồn chưa được xác minh.",
                    [],
                )
            else:
                passed, _reason, verified_or_fallback, checked_citations = await self._guardrails.check_output(
                    final_answer,
                    evidence,
                    query=standalone_query,
                    require_evidence=requires_legal_evidence,
                    claim_verifier=self.deps.claim_verifier,
                    critic_reviewer=getattr(self.deps, "critic_reviewer", None),
                    verification_policy=route_policy,
                    task_type=result.task_type,
                    enforce_legal_safety_circuit_breaker=self.deps.enforce_legal_safety_circuit_breaker,
                )
            verification_error = _reason
            verification_status = _verification_status_for_reason(_reason, valid=passed).value
            citations = checked_citations
            s_ver.close(
                status="ok" if passed else "verification_failed",
                extra_attrs={"passed": passed, "citations_count": len(citations)},
            )
            retryable_verification_failure = any(
                marker in str(_reason).casefold()
                for marker in (
                    "unsupported_claim",
                    "insufficient_evidence",
                    "relevance_check_failed",
                    "not_enough_docs",
                    "content_too_short",
                )
            )
            max_agent_steps = max(1, int(getattr(getattr(self.runner, "config", None), "max_steps", 5)))
            remaining_steps = max_agent_steps - result.steps_taken
            if (
                not passed
                and requires_legal_evidence
                and retryable_verification_failure
                and not await turn_cancelled()
                and remaining_steps > 0
            ):
                previous_searches = [
                    str(step.args.get("query") or "").strip()
                    for step in result.trajectory
                    if step.tool == "search_legal_provisions" and str(step.args.get("query") or "").strip()
                ]
                previous_search_context = (
                    " Các truy vấn đã thử: " + " | ".join(previous_searches[:4]) if previous_searches else ""
                )
                recovery_query = (
                    f"{standalone_query}\n\n"
                    "Yêu cầu tra cứu lại sau kiểm chứng: câu trả lời trước chưa có căn cứ đủ trực tiếp. "
                    "Hãy tra cứu lại bằng thuật ngữ pháp lý chính xác cho từng vấn đề người dùng hỏi; "
                    "nếu câu hỏi gồm quyền lợi và thủ tục, tìm căn cứ cho từng phần riêng. "
                    "Tránh lặp nguyên truy vấn đã thử nếu tài liệu chưa trả lời câu hỏi. "
                    "Trả lời phần được nguồn hỗ trợ, nêu điều kiện chưa rõ thay vì suy đoán, "
                    "và hỏi tối đa một dữ kiện thiết yếu nếu cần."
                    f"{previous_search_context}"
                )
                yield {
                    "type": "status",
                    "message": "Đang tra cứu bổ sung phần căn cứ còn thiếu…",
                    "stage": "search_legal_provisions",
                }
                s_recovery = trace_session.start_span("agent_evidence_recovery")
                async for update in run_agent_pass(recovery_query, max_steps=remaining_steps):
                    yield update
                recovery_result = pass_result
                s_recovery.close(
                    status=(
                        "ok"
                        if recovery_result is not None
                        and recovery_result.termination_reason
                        in {
                            TerminationReason.ANSWER_COMPLETE.value,
                            TerminationReason.RESEARCH_COMPLETE.value,
                        }
                        else "recovery_incomplete"
                    ),
                    extra_attrs={
                        "steps_taken": recovery_result.steps_taken if recovery_result else 0,
                        "evidence_count": len(recovery_result.evidence) if recovery_result else 0,
                    },
                )
                if recovery_result is not None:
                    recovery_result.context_loaded = context_loaded
                    recovery_result.history_messages = history_messages
                    recovery_result.is_follow_up = is_follow_up
                    recovery_result.standalone_query = standalone_query
                if (
                    recovery_result is not None
                    and recovery_result.termination_reason
                    in {
                        TerminationReason.ANSWER_COMPLETE.value,
                        TerminationReason.CACHE_HIT.value,
                        TerminationReason.RESEARCH_COMPLETE.value,
                    }
                    and recovery_result.source not in {"error", "follow_up"}
                ):
                    recovery_evidence = list(recovery_result.evidence)
                    recovery_readiness_reason = ""
                    if self.deps.legal_readiness is not None:
                        try:
                            recovery_readiness = self.deps.legal_readiness.audit()
                            legal_readiness_status = recovery_readiness.status.value
                            legal_readiness_sha = recovery_readiness.manifest_sha256
                            recovery_allowed, recovery_gate_reason = self.deps.legal_readiness.allows_documents(
                                [DocumentRecord.from_dict(document) for document in recovery_evidence]
                            )
                            if not recovery_allowed:
                                recovery_readiness_reason = recovery_gate_reason or recovery_readiness.reason
                        except Exception:  # noqa: BLE001 - the readiness gate remains fail-closed
                            recovery_readiness_reason = "legal_readiness_invalid"
                            legal_readiness_status = "invalid"
                            legal_readiness_sha = self.deps.legal_readiness.manifest_sha256
                    if recovery_readiness_reason:
                        recovery_passed = False
                        recovery_reason = recovery_readiness_reason
                        recovery_answer = (
                            "Tôi chưa thể phát hành câu trả lời vì trạng thái pháp lý của nguồn chưa được xác minh."
                        )
                        recovery_citations: list[dict[str, Any]] = []
                    else:
                        s_recovery_ver = trace_session.start_span("recovery_critic_and_citation_verification")
                        (
                            recovery_passed,
                            recovery_reason,
                            recovery_answer,
                            recovery_citations,
                        ) = await self._guardrails.check_output(
                            recovery_result.answer,
                            recovery_evidence,
                            query=standalone_query,
                            require_evidence=True,
                            claim_verifier=self.deps.claim_verifier,
                            critic_reviewer=getattr(self.deps, "critic_reviewer", None),
                            verification_policy=route_policy,
                            task_type=recovery_result.task_type,
                            enforce_legal_safety_circuit_breaker=self.deps.enforce_legal_safety_circuit_breaker,
                        )
                        s_recovery_ver.close(
                            status="ok" if recovery_passed else "verification_failed",
                            extra_attrs={
                                "passed": recovery_passed,
                                "citations_count": len(recovery_citations),
                            },
                        )
                    if (
                        not recovery_passed
                        and not recovery_readiness_reason
                        and recovery_evidence
                        and "unsupported_claim" in str(recovery_reason).casefold()
                    ):
                        # The autonomous draft and bounded repair can both add
                        # claims beyond the retrieved text. Give the existing
                        # evidence-first answer gateway one final chance to
                        # compose directly from those documents; its output
                        # still passes the same citation, claim, and critic
                        # checks before it can be delivered.
                        yield {
                            "type": "status",
                            "message": "Đang soạn lại câu trả lời trực tiếp từ nguồn đã tra cứu…",
                            "stage": "compose_evidence_answer",
                        }
                        s_compose = trace_session.start_span("evidence_grounded_answer_fallback")
                        composed_answer = ""
                        composed_passed = False
                        composed_reason = ""
                        composed_citations: list[dict[str, Any]] = []
                        try:
                            composed_answer = await self.deps.generation.answer(
                                route_spec(route).task_type.value,
                                standalone_query,
                                [DocumentRecord.from_dict(item) for item in recovery_evidence],
                                understanding.facts.compact(),
                            )
                            if composed_answer.strip():
                                (
                                    composed_passed,
                                    composed_reason,
                                    composed_answer,
                                    composed_citations,
                                ) = await self._guardrails.check_output(
                                    composed_answer,
                                    recovery_evidence,
                                    query=standalone_query,
                                    require_evidence=True,
                                    claim_verifier=self.deps.claim_verifier,
                                    critic_reviewer=getattr(self.deps, "critic_reviewer", None),
                                    verification_policy=route_policy,
                                    task_type=route_spec(route).task_type.value,
                                    enforce_legal_safety_circuit_breaker=self.deps.enforce_legal_safety_circuit_breaker,
                                )
                        except Exception as exc:  # noqa: BLE001 - fallback failure keeps the verified stop
                            composed_reason = f"evidence_answer_fallback_{type(exc).__name__}"
                            logger.info("Evidence-bound answer fallback unavailable: %s", type(exc).__name__)
                        s_compose.close(
                            status="ok" if composed_passed else "verification_failed",
                            extra_attrs={"passed": composed_passed},
                        )
                        if composed_passed:
                            recovery_passed = True
                            recovery_reason = composed_reason
                            recovery_answer = composed_answer
                            recovery_citations = composed_citations
                    if recovery_passed:
                        recovery_result.steps_taken += result.steps_taken
                        result = recovery_result
                        final_answer = recovery_answer or recovery_result.answer
                        verified_or_fallback = final_answer
                        termination_reason = recovery_result.termination_reason
                        citations = recovery_citations
                        source = recovery_result.source
                        evidence = recovery_evidence
                        verification_error = recovery_reason
                        verification_status = _verification_status_for_reason(
                            recovery_reason,
                            valid=True,
                        ).value
                        passed = True
            if not passed:
                final_answer = verified_or_fallback
                termination_reason = TerminationReason.CITATION_VERIFICATION_FAILED.value
                source = "error"
                evidence = []
                citations = []
            elif verified_or_fallback:
                final_answer = verified_or_fallback

        # ── 6. Stream Answer Delivery ──
        if final_answer:
            chunks = split_verified_answer_for_stream(final_answer, max_chunk_chars=self.answer_chunk_size)
            yield {
                "type": "status",
                "message": "Đang hiển thị câu trả lời…",
                "stage": "streaming",
            }
            for idx, chunk in enumerate(chunks, start=1):
                yield {
                    "type": "response_chunk",
                    "chunk": chunk,
                    "chunk_index": idx,
                    "chunk_count": len(chunks),
                    "stage": "streaming",
                }
                if idx < len(chunks) and self.answer_chunk_delay_s:
                    await asyncio.sleep(self.answer_chunk_delay_s)

        # ── 7. Persistence & Telemetry ──
        mock_state: AgentState = {
            "trace_id": trace_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "query": query,
            "standalone_query": standalone_query,
            "context_loaded": context_loaded,
            "history_messages": history_messages,
            "is_follow_up": is_follow_up,
            "answer": final_answer,
            "task_type": route_spec(route).task_type.value,
            "route": route.value,
            "source": source,
            "evidence": evidence,
            "citations": citations,
            "active_case": snapshot.active_case,
            "assessment": result.assessment,
            "awaiting_user_input": result.awaiting_user_input,
            "pipeline_version": "pipeline-agent",
            "termination_reason": termination_reason,
            "action_sequence": [s.tool for s in result.trajectory],
            "run_started_at": started_wall.isoformat(),
            "run_ended_at": datetime.now(UTC).isoformat(),
            "run_duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "preview": preview,
            "citation_error": verification_error,
            "safe_stop_reason": verification_error if verification_error and source == "error" else "",
            "verification_status": verification_status,
            "legal_readiness_status": legal_readiness_status,
            "legal_readiness_sha": legal_readiness_sha,
        }

        try:
            if await turn_cancelled():
                await finish_durable_turn(
                    content="",
                    status="stopped",
                    metadata={
                        "turn_status": "stopped",
                        "trace_id": trace_id,
                        "pipeline_version": "pipeline-agent",
                        "replay_metadata": replay_metadata,
                    },
                    error_code="user_cancelled",
                )
                yield {
                    "type": "response_stopped",
                    "text": "",
                    "turn_status": "stopped",
                    "termination_reason": "user_cancelled",
                    "trace_id": trace_id,
                    "pipeline_version": "pipeline-agent",
                }
                return
            if result.awaiting_user_input and snapshot.active_case:
                await self.deps.history.save_case(user_id, conversation_id, snapshot.active_case)
            if lifecycle.started:
                final = await finish_durable_turn(
                    content=final_answer,
                    status="complete",
                    metadata=_metadata(mock_state),
                )
                if final is None:
                    raise PermissionError("durable turn is not owned by current user")
                mock_state["turn_status"] = str(final.get("status") or "failed")
                mock_state["assistant_message_id"] = str(final.get("assistant_message_id") or "")
                if mock_state["turn_status"] == "stopped":
                    yield {
                        "type": "response_stopped",
                        "text": "",
                        "turn_status": "stopped",
                        "termination_reason": "user_cancelled",
                        "trace_id": trace_id,
                        "pipeline_version": "pipeline-agent",
                    }
                    return
                if mock_state["turn_status"] != "complete":
                    raise RuntimeError("durable agent turn finalization did not complete")
            else:
                await self.deps.history.save_exchange(
                    user_id,
                    conversation_id,
                    query,
                    final_answer,
                    _metadata(mock_state),
                )
            await self.deps.history.record_run(mock_state, started_at, time.perf_counter())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent persistence error: %s", exc)
            try:
                await finish_durable_turn(
                    content="",
                    status="failed",
                    metadata={
                        "turn_status": "failed",
                        "trace_id": trace_id,
                        "pipeline_version": "pipeline-agent",
                    },
                    error_code="storage_unavailable",
                )
            except Exception as finalize_exc:  # noqa: BLE001 - original storage error is authoritative
                logger.debug("Could not mark failed agent turn: %s", finalize_exc)
            trace_session.finish(metadata={"error": "storage_unavailable"})
            yield {
                "type": "error",
                "code": "storage_unavailable",
                "message": "Không thể lưu kết quả. Vui lòng thử lại.",
                "retryable": True,
                "retry_after_seconds": 2,
                "trace_id": trace_id,
                "pipeline_version": "pipeline-agent",
            }
            return

        trace_session.finish(
            metadata={
                "source": source,
                "cache_hit": result.cache_hit,
                "termination": termination_reason,
                "steps_count": len(result.trajectory),
                "context_loaded": context_loaded,
                "history_messages": history_messages,
                "is_follow_up": is_follow_up,
            }
        )

        # ── 8. Complete Event ──
        yield {
            "type": "response_complete",
            "text": final_answer,
            "documents": _documents_for_api(mock_state),
            "source": source,
            "stage": "complete",
            "pipeline_version": "pipeline-agent",
            "termination_reason": termination_reason,
            "trace_id": trace_id,
            "awaiting_user_input": result.awaiting_user_input,
            "trace_summary": trace_session.to_summary(),
            **_metadata(mock_state),
        }

    async def run(self, **kwargs: Any) -> AgentState:
        """Run through the same guarded delivery path as ``stream``.

        ``run`` is used by local integrations that do not consume SSE events.
        Delegating to ``stream`` keeps those callers from receiving an
        unverified autonomous answer or bypassing the chitchat/out-of-scope
        admission checks.
        """

        terminal: dict[str, Any] | None = None
        error_event: dict[str, Any] | None = None
        async for event in self.stream(**kwargs):
            if event.get("type") == "response_complete":
                terminal = dict(event)
            elif event.get("type") == "error":
                error_event = dict(event)

        if terminal is not None:
            state = cast(AgentState, terminal)
            state["query"] = str(kwargs.get("query") or "")
            state["user_id"] = str(kwargs.get("user_id") or "")
            state["conversation_id"] = str(kwargs.get("conversation_id") or "")
            state["answer"] = str(terminal.get("text") or "")
            state["evidence"] = list(terminal.get("documents") or [])
            state["citations"] = list(terminal.get("citations") or [])
            state["source"] = str(terminal.get("source") or "error")
            return state

        return cast(
            AgentState,
            {
                "trace_id": str((error_event or {}).get("trace_id") or kwargs.get("trace_id") or ""),
                "query": str(kwargs.get("query") or ""),
                "user_id": str(kwargs.get("user_id") or ""),
                "conversation_id": str(kwargs.get("conversation_id") or ""),
                "answer": str((error_event or {}).get("message") or "Không thể hoàn thành xử lý câu hỏi."),
                "source": "error",
                "evidence": [],
                "citations": [],
                "termination_reason": str((error_event or {}).get("code") or TerminationReason.ERROR.value),
                "pipeline_version": "pipeline-agent",
            },
        )
