"""Autonomous agent cognitive loop for Vietnamese legal assistance.

Implements the ReAct-style dynamic tool-calling loop (Reason -> Act -> Observe)
with explicit step budgets, loop detection, and structured trajectory logging.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from vietnam_legal_agent.agent.agent_prompt import SYSTEM_PROMPT
from vietnam_legal_agent.agent.planner import AgentBudgetController
from vietnam_legal_agent.agent.tool_registry import ALL_AGENT_TOOLS
from vietnam_legal_agent.domain.legal import explicit_anchors
from vietnam_legal_agent.domain.models import TerminationReason, documents_from_dict
from vietnam_legal_agent.tools.evidence import build_citations, extract_citation_sources

logger = logging.getLogger(__name__)

_SEARCH_ARTICLE_REF_RE = re.compile(
    r"\b(?:điều|khoản|điểm|phụ\s+lục)\s+[\w.-]+",
    flags=re.IGNORECASE,
)
_SEARCH_INSTRUMENT_NUMBER_RE = re.compile(
    r"\b\d{1,5}/\d{4}/(?:NĐ-CP|TT-[A-ZĐ]+|QH\d+|UBTVQH\d+|QĐ-[A-ZĐ]+)\b",
    flags=re.IGNORECASE,
)


def _prepare_legal_search_args(
    user_query: str,
    tool_args: dict[str, Any],
    retrieval_queries: list[str] | None = None,
) -> dict[str, Any]:
    """Preserve user facts and keep hard retrieval anchors user-authored."""

    prepared = dict(tool_args)
    search_query = str(prepared.get("query") or "").strip()
    user_anchors = explicit_anchors(user_query)
    user_articles = {anchor.article.casefold() for anchor in user_anchors if anchor.article}
    user_document_numbers = {anchor.document_number.casefold() for anchor in user_anchors if anchor.document_number}

    def keep_user_article(match: re.Match[str]) -> str:
        return match.group(0) if match.group(0).casefold() in user_articles else " "

    def sanitize_search_text(value: str) -> str:
        sanitized = _SEARCH_ARTICLE_REF_RE.sub(keep_user_article, value)
        sanitized = _SEARCH_INSTRUMENT_NUMBER_RE.sub(
            lambda match: match.group(0)
            if match.group(0).casefold() in user_document_numbers
            else " ",
            sanitized,
        )
        sanitized = re.sub(r"\b(?:theo|điều|khoản|điểm)\s*$", "", sanitized, flags=re.IGNORECASE)
        return " ".join(sanitized.split())

    search_query = sanitize_search_text(search_query)
    normalized_user_query = " ".join(user_query.split())
    normalized_search_query = " ".join(search_query.split())
    # Tool-generated search text commonly repeats the complete user question
    # after a short legal paraphrase. Keep the paraphrase as its own query so
    # it cannot vote twice in the retrieval fusion step.
    if normalized_user_query and normalized_user_query.casefold() in normalized_search_query.casefold():
        search_query = re.sub(
            re.escape(normalized_user_query),
            " ",
            normalized_search_query,
            flags=re.IGNORECASE,
        ).strip()
    else:
        search_query = normalized_search_query
    supplemental_queries = [
        sanitize_search_text(" ".join(str(item or "").split()))
        for item in (retrieval_queries or [])[:2]
    ]
    if user_anchors:
        prepared["required_anchors"] = [anchor.key() for anchor in user_anchors]
    else:
        prepared.pop("required_anchors", None)

    # Search the user's wording independently. A long query formed by joining
    # it to the agent's paraphrase dilutes lexical matches, while duplicate
    # paraphrases can otherwise receive multiple votes during rank fusion.
    prepared["query"] = user_query.strip()
    query_parts: list[str] = []
    seen_queries: set[str] = set()
    # The structured understanding stage has already produced bounded,
    # complementary rewrites. Keep those ahead of a fresh ad-hoc tool rewrite
    # so the latter cannot consume a slot needed by the targeted legal query.
    for part in [*supplemental_queries, search_query]:
        normalized = " ".join(part.split())
        key = normalized.casefold()
        if normalized and key != normalized_user_query.casefold() and key not in seen_queries:
            seen_queries.add(key)
            query_parts.append(normalized)
    if query_parts:
        prepared["related_queries"] = query_parts[:2]
    else:
        prepared.pop("related_queries", None)
    return prepared


@dataclass
class AgentStep:
    """Record of a single action step in the agent's trajectory."""

    step: int
    tool: str
    args: dict[str, Any]
    observation: dict[str, Any]
    latency_ms: float
    allowed: bool
    deny_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "tool": self.tool,
            "args": self.args,
            "latency_ms": self.latency_ms,
            "allowed": self.allowed,
            "deny_reason": self.deny_reason,
            "observation_keys": list(self.observation.keys()),
        }


@dataclass
class AgentRunResult:
    """Final result of an autonomous agent execution."""

    answer: str
    termination_reason: str
    trajectory: list[AgentStep]
    evidence: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    source: str
    steps_taken: int
    cache_hit: bool
    citation_sources: list[dict[str, Any]] = field(default_factory=list)
    question_form: dict[str, Any] | None = None
    allow_skip: bool = False
    financial_calculation: dict[str, Any] | None = None
    awaiting_user_input: bool = False
    follow_up_question: str = ""
    case_state: dict[str, Any] | None = None
    assessment: dict[str, Any] | None = None
    task_type: str = "legal_lookup"
    route: str = "legal_lookup"
    context_loaded: bool = False
    history_messages: int = 0
    is_follow_up: bool = False
    standalone_query: str = ""


@dataclass
class AgentRunConfig:
    """Configuration and guardrail limits for the agent loop."""

    max_steps: int = 5
    max_search_calls: int = 6
    max_web_calls: int = 3
    tool_timeout_s: float = 20.0
    enable_cache: bool = True


ToolCallable = Callable[..., Awaitable[dict[str, Any]]]
CancellationCheck = Callable[[], Awaitable[bool]]


def _cancelled_result(trajectory: list[AgentStep], evidence: list[dict[str, Any]]) -> AgentRunResult:
    return AgentRunResult(
        answer="",
        termination_reason="user_cancelled",
        trajectory=trajectory,
        evidence=evidence,
        citations=[],
        source="error",
        steps_taken=len(trajectory),
        cache_hit=False,
    )


def _tool_result_status(observation: dict[str, Any]) -> tuple[str, str | None]:
    error = str(observation.get("error") or "")
    if observation.get("budget_denied"):
        return "denied", error or "budget_denied"
    if "timed out" in error:
        return "timed_out", "tool_timeout"
    if observation.get("ok") is False or error:
        return "failed", error.split(":", 1)[0] or "tool_failed"
    return "completed", None


def _evidence_identity(document: dict[str, Any]) -> str:
    metadata = dict(document.get("metadata") or {})
    source = str(document.get("source") or metadata.get("source_kind") or "legal")
    if source == "web":
        url = str(metadata.get("official_url") or metadata.get("url") or "").strip().rstrip("/").casefold()
        if url:
            return f"web:{url}"
    document_id = str(
        document.get("document_id")
        or metadata.get("chunk_id")
        or metadata.get("source_document_id")
        or metadata.get("id")
        or ""
    ).strip()
    if document_id:
        return f"{source}:{document_id}"
    content = str(document.get("content") or document.get("page_content") or "").strip()
    return f"{source}:sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _append_evidence_documents(
    all_evidence: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> list[int]:
    """Append distinct evidence and return its stable global citation indices."""

    known_indices = {
        _evidence_identity(document): index
        for index, document in enumerate(all_evidence, start=1)
    }
    citation_indices: list[int] = []
    for document in documents:
        identity = _evidence_identity(document)
        index = known_indices.get(identity)
        if index is None:
            all_evidence.append(document)
            index = len(all_evidence)
            known_indices[identity] = index
        citation_indices.append(index)
    return citation_indices


def _compact_observation_for_agent(
    tool_name: str,
    observation: dict[str, Any],
    *,
    citation_indices: list[int] | None = None,
) -> dict[str, Any]:
    """Trim excessive text and verbose metadata from observations to preserve token budget."""
    if not isinstance(observation, dict):
        return observation

    # For document retrieval, keep essential statutory identifiers and concise content excerpts
    if "documents" in observation and isinstance(observation["documents"], list):
        compacted_docs = []
        for local_index, doc in enumerate(observation["documents"][:4]):
            if not isinstance(doc, dict):
                continue
            content = str(doc.get("content") or doc.get("page_content") or "")[:800]
            meta = dict(doc.get("metadata") or {})
            essential_meta = {
                k: meta[k]
                for k in (
                    "Dieu", "Chuong", "Muc", "Document_Number", "Source_Title",
                    "source_title", "legal_anchor", "anchor", "law_ref",
                    "source", "title", "url", "official_url"
                )
                if k in meta
            }
            compacted_docs.append({
                "content": content,
                "metadata": essential_meta,
                "document_id": doc.get("document_id", ""),
                "score": doc.get("score"),
                "citation_index": (
                    citation_indices[local_index]
                    if citation_indices and local_index < len(citation_indices)
                    else local_index + 1
                ),
            })
        return {
            **{k: v for k, v in observation.items() if k != "documents"},
            "documents": compacted_docs,
            "total_found": len(observation["documents"]),
        }

    return observation


class VietnameseLegalAgentRunner:
    """Autonomous ReAct runner for supported Vietnamese legal assistance."""

    def __init__(
        self,
        config: AgentRunConfig | None = None,
        llm: Any | None = None,
        tools: list[ToolCallable] | None = None,
    ) -> None:
        self.config = config or AgentRunConfig()
        self.tools: list[ToolCallable] = tools if tools is not None else cast(list[ToolCallable], ALL_AGENT_TOOLS)
        self._tools_map: dict[str, ToolCallable] = {
            getattr(tool, "__name__", ""): tool for tool in self.tools
        }

        if llm is not None:
            self._llm = llm
        else:
            from vietnam_legal_agent.infra.llm_instances import get_llm_router

            self._llm = get_llm_router().bind_tools(self.tools)

        self._budget = AgentBudgetController(
            max_steps=self.config.max_steps,
            max_search_calls=self.config.max_search_calls,
            max_web_calls=self.config.max_web_calls,
        )

    async def run(
        self,
        query: str,
        *,
        history: list[dict[str, Any]] | None = None,
        active_case: dict[str, Any] | None = None,
        history_summary: str = "",
        mode: str = "auto",
        trace_id: str = "",
        require_legal_evidence: bool | None = None,
        retrieval_queries: list[str] | None = None,
        search_user_query: str | None = None,
        is_cancelled: CancellationCheck | None = None,
    ) -> AgentRunResult:
        """Execute the agent loop synchronously and return the complete result."""
        result: AgentRunResult | None = None
        async for event in self.stream(
            query,
            history=history,
            active_case=active_case,
            history_summary=history_summary,
            mode=mode,
            trace_id=trace_id,
            require_legal_evidence=require_legal_evidence,
            retrieval_queries=retrieval_queries,
            search_user_query=search_user_query,
            is_cancelled=is_cancelled,
        ):
            if event.get("type") == "agent_complete":
                result = event["result"]

        if result is None:
            return AgentRunResult(
                answer="Không thể hoàn thành xử lý câu hỏi.",
                termination_reason=TerminationReason.ERROR.value,
                trajectory=[],
                evidence=[],
                citations=[],
                source="error",
                steps_taken=0,
                cache_hit=False,
            )
        return result

    async def stream(
        self,
        query: str,
        *,
        history: list[dict[str, Any]] | None = None,
        active_case: dict[str, Any] | None = None,
        history_summary: str = "",
        mode: str = "auto",
        trace_id: str = "",
        require_legal_evidence: bool | None = None,
        retrieval_queries: list[str] | None = None,
        search_user_query: str | None = None,
        is_cancelled: CancellationCheck | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute the agent loop, streaming step status events and final result."""
        trajectory: list[AgentStep] = []
        all_evidence: list[dict[str, Any]] = []
        cache_hit = False
        assessment_payload: dict[str, Any] | None = None
        financial_payload: dict[str, Any] | None = None

        messages = self._build_initial_messages(
            query,
            history=history or [],
            active_case=active_case,
            history_summary=history_summary,
            mode=mode,
            retrieval_queries=retrieval_queries,
        )

        step = 0
        for step in range(self.config.max_steps):
            if not self._budget.within_step_budget(step):
                break
            if is_cancelled is not None and await is_cancelled():
                yield {"type": "agent_complete", "result": _cancelled_result(trajectory, all_evidence)}
                return

            # ── 1. REASON: Call LLM to deliberate and choose action ──
            try:
                response = await self._llm.ainvoke(messages)
            except asyncio.CancelledError:
                logger.info("Agent loop LLM call cancelled by client at step %d", step)
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("LLM call failed at step %d: %s", step, exc)
                yield {
                    "type": "agent_complete",
                    "result": AgentRunResult(
                        answer="Đã xảy ra lỗi khi kết nối với mô hình ngôn ngữ.",
                        termination_reason=TerminationReason.ERROR.value,
                        trajectory=trajectory,
                        evidence=all_evidence,
                        citations=[],
                        source="error",
                        steps_taken=step + 1,
                        cache_hit=False,
                    ),
                }
                return

            messages.append(response)

            # ── 2. TERMINATION CHECK: No tool calls means agent composed final answer ──
            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                answer = str(getattr(response, "content", "") or "").strip()
                # Routes that require legal evidence must search even if the
                # model emits a short draft; answer length is not a proxy for
                # whether the user asked a substantive legal question.
                legacy_should_search = (
                    require_legal_evidence is None
                    and len(answer) > 40
                    and not any(
                        w in answer.lower()
                        for w in (
                            "xin chào",
                            "chào bạn",
                            "hello",
                            "hi",
                            "bạn là ai",
                            "hẹn gặp lại",
                            "cảm ơn bạn",
                        )
                    )
                )
                if (
                    not all_evidence
                    and not cache_hit
                    and step < self.config.max_steps - 1
                    and (require_legal_evidence is True or legacy_should_search)
                ):
                    messages.append({
                        "role": "user",
                        "content": "Yêu cầu bắt buộc: Câu trả lời cần có căn cứ pháp lý. Hãy gọi tool `search_legal_provisions` với từ khóa trọng tâm để tra cứu quy định pháp luật trước khi kết luận.",
                    })
                    continue

                doc_records = documents_from_dict(all_evidence)
                from vietnam_legal_agent.tools.evidence import auto_anchor_citations_in_answer
                answer = auto_anchor_citations_in_answer(answer, doc_records)
                citation_sources = [cs.to_dict() for cs in extract_citation_sources(answer, doc_records)]
                citations = [c.to_dict() for c in build_citations(doc_records)]

                yield {
                    "type": "agent_complete",
                    "result": AgentRunResult(
                        answer=answer,
                        termination_reason=(
                            TerminationReason.CACHE_HIT.value
                            if cache_hit
                            else TerminationReason.ANSWER_COMPLETE.value
                        ),
                        trajectory=trajectory,
                        evidence=all_evidence,
                        citations=citations,
                        citation_sources=citation_sources,
                        source="cache" if cache_hit else "legal",
                        steps_taken=step + 1,
                        cache_hit=cache_hit,
                        assessment=assessment_payload,
                        financial_calculation=financial_payload,
                    ),
                }
                return

            # ── 3. ACT & OBSERVE: Execute each tool requested by LLM ──
            for tool_call in tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {}) or {}
                if tool_name == "search_legal_provisions":
                    tool_args = _prepare_legal_search_args(
                        search_user_query or query,
                        tool_args,
                        retrieval_queries=retrieval_queries,
                    )
                call_id = tool_call.get("id", f"call_{step}_{tool_name}")

                yield {
                    "type": "agent_tool_call",
                    "step": step + 1,
                    "tool": tool_name,
                    "args": tool_args,
                    "trace_id": trace_id,
                }

                if is_cancelled is not None and await is_cancelled():
                    yield {"type": "agent_complete", "result": _cancelled_result(trajectory, all_evidence)}
                    return

                # Budget check & loop detection
                history_for_budget = [{"tool": s.tool, "args": s.args} for s in trajectory]
                budget_check = self._budget.check_tool_call(tool_name, tool_args, history_for_budget)

                if not budget_check.allowed:
                    denial_obs = {
                        "ok": False,
                        "error": budget_check.reason,
                        "budget_denied": True,
                    }
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(denial_obs, ensure_ascii=False),
                    })
                    trajectory.append(
                        AgentStep(
                            step=step,
                            tool=tool_name,
                            args=tool_args,
                            observation=denial_obs,
                            latency_ms=0.0,
                            allowed=False,
                            deny_reason=budget_check.reason,
                        )
                    )
                    yield {
                        "type": "agent_tool_result",
                        "step": step + 1,
                        "tool": tool_name,
                        "status": "denied",
                        "latency_ms": 0.0,
                        "error_code": budget_check.reason.split(":", 1)[0],
                        "trace_id": trace_id,
                    }
                    continue

                # Execute the tool
                started = time.perf_counter()
                observation = await self._execute_tool(tool_name, tool_args)
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                status, error_code = _tool_result_status(observation)

                trajectory.append(
                    AgentStep(
                        step=step,
                        tool=tool_name,
                        args=tool_args,
                        observation=observation,
                        latency_ms=latency_ms,
                        allowed=True,
                    )
                )
                yield {
                    "type": "agent_tool_result",
                    "step": step + 1,
                    "tool": tool_name,
                    "status": status,
                    "latency_ms": latency_ms,
                    "error_code": error_code,
                    "trace_id": trace_id,
                }

                if is_cancelled is not None and await is_cancelled():
                    yield {"type": "agent_complete", "result": _cancelled_result(trajectory, all_evidence)}
                    return

                # Give every source a stable global index across all retrieval
                # calls. Tool-local indexes restart at one and cannot be used
                # as citations after evidence from multiple searches is joined.
                citation_indices: list[int] = []
                if "documents" in observation and isinstance(observation["documents"], list):
                    citation_indices = _append_evidence_documents(
                        all_evidence,
                        observation["documents"],
                    )
                elif (
                    tool_name == "lookup_answer_cache"
                    and observation.get("hit")
                    and isinstance(observation.get("evidence"), list)
                ):
                    citation_indices = _append_evidence_documents(
                        all_evidence,
                        observation["evidence"],
                    )

                # Track cache
                if tool_name == "lookup_answer_cache" and observation.get("hit"):
                    cache_hit = True

                # Track assessment results
                if tool_name == "evaluate_legal_case" and observation.get("ok"):
                    assessment_payload = observation

                # Track financial calculation results
                if tool_name == "calculate_statutory_amounts" and observation.get("ok"):
                    financial_payload = observation

                # Handle clarification action (Open-Design Pattern with Skip affordance)
                if tool_name == "ask_user_for_clarification" or observation.get("awaiting_user_input"):
                    question = observation.get("question") or "Bạn có thể cung cấp thêm thông tin cần thiết không?"

                    # If the user asked a substantive legal question, urge the agent to search and provide direct consultation
                    has_substantive_inquiry = any(
                        kw in query.lower()
                        for kw in (
                            "co duoc", "có được", "ai se", "ai sẽ", "chia the nao", "chia thế nào",
                            "bao nhieu", "nộp đơn", "nop don", "khoi kien", "khởi kiện",
                            "nuoi con", "nuôi con", "the nao", "thế nào", "tang gia", "tăng giá",
                            "duoc khong", "được không"
                        )
                    )
                    if has_substantive_inquiry and step < 2 and not all_evidence:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": json.dumps({
                                "status": "clarification_recorded",
                                "instruction": (
                                    "Người dùng đang hỏi trực tiếp về quyền và nghĩa vụ pháp lý. "
                                    "Bạn BẮT BUỘC phải gọi `search_legal_provisions` để tra cứu căn cứ điều luật và giải đáp trực tiếp câu hỏi của người dùng trước, "
                                    "sau đó mới đính kèm gợi ý làm rõ ở cuối câu trả lời."
                                ),
                            }, ensure_ascii=False),
                        })
                        continue

                    yield {
                        "type": "agent_complete",
                        "result": AgentRunResult(
                            answer=question,
                            termination_reason=TerminationReason.AWAITING_USER_INPUT.value,
                            trajectory=trajectory,
                            evidence=[],
                            citations=[],
                            citation_sources=[],
                            source="follow_up",
                            steps_taken=step + 1,
                            cache_hit=False,
                            awaiting_user_input=True,
                            follow_up_question=question,
                            case_state={
                                "status": "collecting",
                                "missing_facts": [],
                            },
                        ),
                    }
                    return

                # Compact observation for message scratchpad to avoid token bloat
                compacted_obs = _compact_observation_for_agent(
                    tool_name,
                    observation,
                    citation_indices=citation_indices,
                )

                # Append tool observation to message scratchpad
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": (
                        json.dumps(compacted_obs, ensure_ascii=False)
                        if isinstance(compacted_obs, dict)
                        else str(compacted_obs)
                    ),
                })

        # ── 4. MAX STEPS REACHED: Safe termination fallback ──
        doc_records = documents_from_dict(all_evidence)
        citation_sources = [cs.to_dict() for cs in extract_citation_sources("", doc_records)]
        citations = [c.to_dict() for c in build_citations(doc_records)]

        yield {
            "type": "agent_complete",
            "result": AgentRunResult(
                answer="Tôi chưa thể tìm đủ căn cứ pháp lý để đưa ra kết luận an toàn sau các bước tra cứu.",
                termination_reason=TerminationReason.INSUFFICIENT_EVIDENCE.value,
                trajectory=trajectory,
                evidence=all_evidence,
                citations=citations,
                citation_sources=citation_sources,
                source="error",
                steps_taken=step + 1,
                cache_hit=False,
                assessment=assessment_payload,
                financial_calculation=financial_payload,
            ),
        }

    def _build_initial_messages(
        self,
        query: str,
        *,
        history: list[dict[str, Any]],
        active_case: dict[str, Any] | None,
        history_summary: str,
        mode: str,
        retrieval_queries: list[str] | None = None,
    ) -> list[Any]:
        messages: list[Any] = [("system", SYSTEM_PROMPT)]
        normalized_retrieval_queries = [
            " ".join(str(item or "").split())[:1000]
            for item in (retrieval_queries or [])[:2]
            if " ".join(str(item or "").split())
        ]
        if normalized_retrieval_queries:
            messages.append(
                (
                    "system",
                    (
                        "<legal_retrieval_query_hints>\n"
                        "Dùng các cụm dưới đây làm gợi ý cho tool search_legal_provisions; giữ nguyên dữ kiện của người dùng "
                        "và chỉ dùng chúng để tìm nguồn, không coi chúng là dữ kiện hay kết luận pháp lý.\n"
                        f"{json.dumps(normalized_retrieval_queries, ensure_ascii=False)}\n"
                        "</legal_retrieval_query_hints>"
                    ),
                )
            )
        if history or active_case or history_summary:
            context_dict = {
                "recent_history": [
                    {"role": h.get("role", ""), "content": str(h.get("content", ""))[:500]}
                    for h in history[-4:]
                ],
                "history_summary": history_summary[:600],
                "active_case": active_case or {},
                "mode": mode,
            }
            messages.append(
                (
                    "system",
                    f"<conversation_context>\n{json.dumps(context_dict, ensure_ascii=False)}\n</conversation_context>",
                )
            )
        messages.append(("human", query))
        return messages

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool_func = self._tools_map.get(name)
        if tool_func is None:
            return {"error": f"Unknown tool: '{name}'", "ok": False}
        try:
            result = await asyncio.wait_for(tool_func(**args), timeout=self.config.tool_timeout_s)
            return result if isinstance(result, dict) else {"result": result, "ok": True}
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return {"error": f"Tool '{name}' timed out after {self.config.tool_timeout_s}s", "ok": False}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}", "ok": False}
