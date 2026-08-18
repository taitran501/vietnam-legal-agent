"""Streaming presenter for the bounded workflow."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
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
    "validate_input": "Đã kiểm tra nội dung câu hỏi.",
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


def split_verified_answer_for_stream(answer: str, *, max_chunk_chars: int = 180) -> list[str]:
    """Split an already verified answer into display-sized SSE chunks.

    The workflow intentionally does not emit legal claims while citation
    verification is still pending.  Once the verifier has accepted the final
    answer, this helper preserves the exact text while producing enough
    bounded chunks for the client to render progressive output.
    """

    if not answer:
        return []
    if max_chunk_chars < 1:
        raise ValueError("max_chunk_chars must be positive")

    chunks: list[str] = []
    current = ""
    for token in re.findall(r"\S+(?:\s+|$)", answer):
        # A long URL or legal identifier should never block streaming.
        while len(token) > max_chunk_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(token[:max_chunk_chars])
            token = token[max_chunk_chars:]
        if current and len(current) + len(token) > max_chunk_chars:
            chunks.append(current)
            current = token
        else:
            current += token
    if current:
        chunks.append(current)
    return chunks


def _documents_for_api(state: AgentState) -> list[dict[str, Any]]:
    allowed_metadata = {
        "document_id", "Document_Id", "Document_Number", "source_title", "Source_Title", "title",
        "instrument_number", "anchor", "legal_anchor", "Dieu", "Chuong", "Khoan", "Diem",
        "Pages", "page", "page_start", "page_end", "Source_Start", "Source_End", "offset_start", "offset_end",
        "source_uri", "Source_URI", "official_url", "url", "authority", "source_kind", "effective_status", "Effective_Status", "amendment_relationship", "Amendment_Relationship",
        "Effective_From", "Effective_To", "effective_from", "effective_to", "Source_SHA256", "chunk_id",
        "Corpus_Version", "Corpus_SHA256", "corpus_as_of_date", "rule_id", "source_file", "Source_File",
        "Active_Source_Document_Id", "Active_Source_Pages", "Amendment_Resolution_Status", "Amendment_Operations", "Current_Law_Support",
    }
    documents: list[dict[str, Any]] = []
    used_indices = {int(value) for value in re.findall(r"\[(\d+)\]", state.get("answer", ""))}
    for citation_index, item in enumerate(state.get("evidence", []), start=1):
        if used_indices and citation_index not in used_indices:
            continue
        metadata = dict(item.get("metadata") or {})
        safe_metadata = {key: metadata[key] for key in allowed_metadata if key in metadata}
        safe_metadata.setdefault("document_id", item.get("document_id", ""))
        safe_metadata["citation_index"] = citation_index
        if state.get("corpus_as_of_date"):
            safe_metadata.setdefault("corpus_as_of_date", state.get("corpus_as_of_date"))
        excerpt_limit = 1200 if item.get("source") == "web" else 2000
        safe_metadata["excerpt"] = str(item.get("content", ""))[:excerpt_limit]
        documents.append(
            {
                "page_content": str(item.get("content", ""))[:excerpt_limit],
                "metadata": safe_metadata,
                "document_id": item.get("document_id", ""),
                "score": item.get("score"),
                "source": item.get("source", ""),
            }
        )
    return documents


def _source_snapshots(state: AgentState) -> list[dict[str, Any]]:
    used_indices = {int(value) for value in re.findall(r"\[(\d+)\]", state.get("answer", ""))}
    return [
        {
            "citation_index": citation_index,
            "source_id": str((item.get("metadata") or {}).get("chunk_id") or item.get("document_id") or ""),
            "title": str((item.get("metadata") or {}).get("Source_Title") or (item.get("metadata") or {}).get("source_title") or (item.get("metadata") or {}).get("title") or item.get("source") or ""),
            "instrument_number": str((item.get("metadata") or {}).get("Document_Number") or (item.get("metadata") or {}).get("instrument_number") or ""),
            "anchor": str((item.get("metadata") or {}).get("legal_anchor") or (item.get("metadata") or {}).get("anchor") or (item.get("metadata") or {}).get("Dieu") or ""),
            "page": (item.get("metadata") or {}).get("Pages") or (item.get("metadata") or {}).get("page"),
            "offset_start": (item.get("metadata") or {}).get("Source_Start") or (item.get("metadata") or {}).get("offset_start"),
            "offset_end": (item.get("metadata") or {}).get("Source_End") or (item.get("metadata") or {}).get("offset_end"),
            "official_url": str((item.get("metadata") or {}).get("official_url") or (item.get("metadata") or {}).get("url") or (item.get("metadata") or {}).get("Source_URI") or (item.get("metadata") or {}).get("source_uri") or ""),
            "source_kind": str((item.get("metadata") or {}).get("source_kind") or item.get("source") or "legal_corpus"),
            "authority": str((item.get("metadata") or {}).get("authority") or ("official" if item.get("source") == "legal" else "unknown")),
            "effective_status": str((item.get("metadata") or {}).get("Effective_Status") or (item.get("metadata") or {}).get("effective_status") or "unknown"),
            "effective_from": (item.get("metadata") or {}).get("Effective_From") or (item.get("metadata") or {}).get("effective_from"),
            "effective_to": (item.get("metadata") or {}).get("Effective_To") or (item.get("metadata") or {}).get("effective_to"),
            "amendment_relationship": (item.get("metadata") or {}).get("Amendment_Relationship") or (item.get("metadata") or {}).get("amendment_relationship") or [],
            "active_source_document_id": str((item.get("metadata") or {}).get("Active_Source_Document_Id") or ""),
            "active_source_pages": str((item.get("metadata") or {}).get("Active_Source_Pages") or ""),
            "amendment_resolution_status": str((item.get("metadata") or {}).get("Amendment_Resolution_Status") or ""),
            "amendment_operations": (item.get("metadata") or {}).get("Amendment_Operations") or [],
            "current_law_support": bool((item.get("metadata") or {}).get("Current_Law_Support", False)),
            "corpus_as_of_date": str(state.get("corpus_as_of_date") or ""),
            "excerpt": str(item.get("content") or "")[:1200 if item.get("source") == "web" else 2000],
        }
        for citation_index, item in enumerate(state.get("evidence", []), start=1)
        if not used_indices or citation_index in used_indices
    ]


def _metadata(state: AgentState) -> dict[str, Any]:
    checklist = state.get("checklist", [])
    assumptions = [item.get("assumption") for item in checklist if item.get("assumption")]
    if state.get("assessment"):
        assumptions.extend(
            item for item in (state.get("assessment") or {}).get("assumptions", []) if item
        )
        if not assumptions:
            assumptions.append("Kết quả đánh giá là sơ bộ và phụ thuộc vào thông tin doanh nghiệp đã cung cấp.")
    return {
        "task_type": state.get("task_type", TaskType.LEGAL_LOOKUP.value),
        "route": state.get("route", "legal_lookup"),
        "source_scope": state.get("source_scope", "legal_corpus"),
        "corpus_version": state.get("corpus_version", ""),
        "corpus_sha": state.get("corpus_sha", ""),
        "embedding_profile": state.get("embedding_profile", ""),
        "evidence_status": state.get("evidence_status", "not_evaluated"),
        "available_actions": state.get("available_actions", []),
        "case_state": state.get("case_state"),
        "assessment": state.get("assessment"),
        "checklist": checklist,
        "assumptions": assumptions,
        "missing_facts": state.get("missing_facts", []),
        "citations": state.get("citations", []),
        "evidence_assessment": state.get("evidence_assessment", {}),
        "trace_id": state.get("trace_id", ""),
        "corpus_id": state.get("corpus_id", "epr"),
        "corpus_as_of_date": state.get("corpus_as_of_date", ""),
        "preview": bool(state.get("preview", False)),
        "pipeline_version": state.get("pipeline_version", "pipeline-v3"),
        "termination_reason": state.get("termination_reason", TerminationReason.ERROR.value),
        "outcome": state.get("outcome"),
        "result_type": state.get("result_type"),
        "required_issues": state.get("required_issues", []),
        "covered_issues": state.get("covered_issues", []),
        "assistant_message_id": state.get("assistant_message_id", ""),
        "sources": state.get("sources") or _source_snapshots(state),
        "replay_metadata": state.get("replay_metadata") or {},
        "validation_errors": state.get("validation_errors") or {},
        "rule_id": state.get("rule_id", ""),
        "citation_error": state.get("citation_error", ""),
        "safe_stop_reason": state.get("safe_stop_reason", ""),
    }


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
                TaskType.ASSESS_EPR_OBLIGATION.value,
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
        state = await run_workflow(deps=self.deps, compiled_workflow=self._compiled_workflow, **kwargs)
        from backend.config import get_settings

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
        try:
            state = await create_initial_state(deps=self.deps, **kwargs)
            from backend.config import get_settings

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
                "pipeline_version": "pipeline-v3",
            }


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

        from epr_agent.agent.guardrails import AgentGuardrails

        self._guardrails = guardrails or AgentGuardrails()
        self._runner = runner

    @property
    def runner(self) -> Any:
        if self._runner is None:
            from epr_agent.agent.agent_loop import AgentRunConfig, EprAgentRunner

            self._runner = EprAgentRunner(
                config=AgentRunConfig(max_steps=5, max_search_calls=4, max_web_calls=1)
            )
        return self._runner

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        query = str(kwargs.get("query") or "").strip()
        user_id = str(kwargs.get("user_id") or "")
        conversation_id = str(kwargs.get("conversation_id") or "")
        trace_id = str(kwargs.get("trace_id") or uuid.uuid4())
        mode = str(kwargs.get("mode") or "auto")
        started_at = time.perf_counter()
        started_wall = datetime.now(UTC)

        from backend.config import get_settings
        from epr_agent.tracing.trace_context import get_trace_store

        preview = get_settings().corpus_runtime_mode == "preview"
        trace_session = get_trace_store().create_trace(
            trace_id=trace_id,
            conversation_id=conversation_id,
            user_id=user_id,
            query=query,
        )

        # ── 1. Input Validation Guardrail ──
        s_val = trace_session.start_span("validate_input")
        yield {"type": "status", "message": "Đang kiểm tra câu hỏi…", "stage": "validate_input"}
        is_valid, _input_reason = self._guardrails.check_input(query)
        s_val.close(status="ok" if is_valid else "invalid")
        if not is_valid:
            safe_msg = (
                "Câu hỏi cần có nội dung và không vượt quá 3.000 ký tự. Bạn hãy gửi lại câu hỏi ngắn gọn hơn."
            )
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

        # ── 2. Context Loading ──
        s_ctx = trace_session.start_span("load_context")
        yield {"type": "status", "message": "Đang nạp ngữ cảnh cuộc trò chuyện…", "stage": "load_context"}
        snapshot = await self.deps.history.load(user_id, conversation_id, max_messages=6)
        s_ctx.close(extra_attrs={"history_len": len(snapshot.history)})

        # ── 3. Fast Bypass for Chitchat & Out of Scope ──
        from epr_agent.domain.tasks import classify_route

        route = classify_route(query, snapshot.history, snapshot.active_case)
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
            await self.deps.history.save_exchange(
                user_id,
                conversation_id,
                query,
                answer,
                {"pipeline_version": "pipeline-agent", "route": "chitchat", "source": "chitchat"},
            )
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
        _tool_status_messages = {
            "search_legal_provisions": "Đang tra cứu kho văn bản pháp luật…",
            "search_web_official": "Đang tìm kiếm thông tin từ cổng chính thức…",
            "lookup_answer_cache": "Đang kiểm tra bộ nhớ đệm câu trả lời…",
            "evaluate_epr_obligation": "Đang đối chiếu quy định và tính toán nghĩa vụ…",
            "get_case_form_fields": "Đang kiểm tra thông tin tình huống…",
            "load_conversation_context": "Đang nạp ngữ cảnh hội thoại…",
            "ask_user_for_clarification": "Đang soạn câu hỏi làm rõ thông tin…",
        }

        s_loop = trace_session.start_span("agent_cognitive_loop")
        result = None
        async for event in self.runner.stream(
            query,
            history=snapshot.history,
            active_case=snapshot.active_case,
            history_summary=snapshot.summary,
            mode=mode,
            trace_id=trace_id,
        ):
            if event.get("type") == "agent_tool_call":
                tool_name = event.get("tool", "")
                msg = _tool_status_messages.get(tool_name, "Đang xử lý bước tiếp theo…")
                s_tool = trace_session.start_span(f"tool:{tool_name}")
                s_tool.close(extra_attrs={"step": event.get("step", 1)})
                yield {
                    "type": "workflow_step",
                    "step": event.get("step", 1),
                    "action": tool_name,
                    "status": "completed",
                    "trace_id": trace_id,
                }
                yield {
                    "type": "status",
                    "message": msg,
                    "stage": tool_name,
                }
            elif event.get("type") == "agent_complete":
                result = event.get("result")

        s_loop.close(
            model="gpt-4o-mini",
            input_tokens=len(query) * 2,
            output_tokens=len(result.answer if result else "") // 3,
            extra_attrs={"steps_taken": result.steps_taken if result else 0},
        )

        if result is None:
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

        # ── 5. Output Verification Guardrail ──
        final_answer = result.answer
        termination_reason = result.termination_reason
        citations = list(result.citations)
        source = result.source
        evidence = list(result.evidence)

        if (
            termination_reason == TerminationReason.ANSWER_COMPLETE.value
            and source not in {"error", "follow_up"}
            and not result.cache_hit
        ):
            s_ver = trace_session.start_span("critic_and_citation_verification")
            yield {"type": "status", "message": "Đang xác minh căn cứ pháp lý và thẩm định phản biện…", "stage": "verify"}
            passed, _reason, verified_or_fallback, checked_citations = await self._guardrails.check_output(
                final_answer,
                evidence,
                query=query,
                claim_verifier=self.deps.claim_verifier,
                critic_reviewer=getattr(self.deps, "critic_reviewer", None),
            )
            citations = checked_citations
            s_ver.close(
                status="ok" if passed else "verification_failed",
                extra_attrs={"passed": passed, "citations_count": len(citations)},
            )
            if not passed:
                final_answer = verified_or_fallback
                termination_reason = TerminationReason.CITATION_VERIFICATION_FAILED.value
                source = "error"
                evidence = []
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
            "query": query,
            "answer": final_answer,
            "task_type": result.task_type,
            "route": result.route,
            "source": source,
            "evidence": evidence,
            "citations": citations,
            "active_case": snapshot.active_case,
            "case_state": result.case_state,
            "assessment": result.assessment,
            "awaiting_user_input": result.awaiting_user_input,
            "pipeline_version": "pipeline-agent",
            "termination_reason": termination_reason,
            "action_sequence": [s.tool for s in result.trajectory],
            "run_started_at": started_wall.isoformat(),
            "run_ended_at": datetime.now(UTC).isoformat(),
            "run_duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "preview": preview,
        }

        try:
            if result.awaiting_user_input and snapshot.active_case:
                await self.deps.history.save_case(user_id, conversation_id, snapshot.active_case)
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

        trace_session.finish(
            metadata={
                "source": source,
                "cache_hit": result.cache_hit,
                "termination": termination_reason,
                "steps_count": len(result.trajectory),
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
            "case_state": result.case_state,
            "trace_summary": trace_session.to_summary(),
            **_metadata(mock_state),
        }

    async def run(self, **kwargs: Any) -> AgentState:
        """Run and return AgentState for testing compatibility."""
        query = str(kwargs.get("query") or "")
        user_id = str(kwargs.get("user_id") or "")
        conversation_id = str(kwargs.get("conversation_id") or "")
        trace_id = str(kwargs.get("trace_id") or uuid.uuid4())
        started_at = time.perf_counter()
        started_wall = datetime.now(UTC)

        snapshot = await self.deps.history.load(user_id, conversation_id, max_messages=6)
        result = await self.runner.run(
            query,
            history=snapshot.history,
            active_case=snapshot.active_case,
            history_summary=snapshot.summary,
            trace_id=trace_id,
        )

        from backend.config import get_settings

        state: AgentState = {
            "trace_id": trace_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "query": query,
            "answer": result.answer,
            "task_type": result.task_type,
            "route": result.route,
            "source": result.source,
            "evidence": result.evidence,
            "citations": result.citations,
            "active_case": snapshot.active_case,
            "case_state": result.case_state,
            "assessment": result.assessment,
            "awaiting_user_input": result.awaiting_user_input,
            "pipeline_version": "pipeline-agent",
            "termination_reason": result.termination_reason,
            "action_sequence": [s.tool for s in result.trajectory],
            "run_started_at": started_wall.isoformat(),
            "run_ended_at": datetime.now(UTC).isoformat(),
            "run_duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "preview": get_settings().corpus_runtime_mode == "preview",
        }
        return state


@lru_cache(maxsize=1)
def get_default_runtime() -> WorkflowRuntime:
    # Runtime selection is server-owned. The public request schema has no
    # pipeline field, so a browser cannot force an experimental workflow.
    from backend.config import get_settings

    version = get_settings().agent_pipeline_version
    if version == "pipeline-agent":
        return AgentWorkflowRuntime(default_dependencies())  # type: ignore[return-value]
    if version == "pipeline-v4":
        from epr_agent.agent.v4 import V4WorkflowRuntime

        return V4WorkflowRuntime(default_dependencies())
    return WorkflowRuntime(default_dependencies())


async def stream_chat(
    *,
    query: str,
    user_id: str,
    conversation_id: str,
    legacy_session_id: str = "",
    mode: str = "auto",
    operation: str = "message",
    intent_hint: str = "auto",
    interaction_source: str = "composer",
    case_patch: dict[str, Any] | None = None,
    fact_updates: dict[str, dict[str, Any]] | None = None,
    replay_metadata: dict[str, Any] | None = None,
    turn_id: str = "",
    target_assistant_message_id: int | None = None,
    runtime: WorkflowRuntime | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Public SSE event generator used by the compatibility API route."""

    selected = runtime or get_default_runtime()
    request_kwargs: dict[str, Any] = {
        "query": query,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "legacy_session_id": legacy_session_id,
        "mode": mode,
    }
    if selected.__class__.__name__ == "V4WorkflowRuntime":
        request_kwargs.update(
            operation=operation,
            intent_hint=intent_hint,
            interaction_source=interaction_source,
            case_patch=case_patch or {},
            fact_updates=fact_updates or {},
            replay_metadata=replay_metadata or {},
            turn_id=turn_id,
            target_assistant_message_id=target_assistant_message_id,
        )
    async for event in selected.stream(**request_kwargs):
        yield event

