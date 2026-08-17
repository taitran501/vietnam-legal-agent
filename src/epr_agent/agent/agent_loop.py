"""Autonomous Agent Cognitive Loop for EPR Legal Assistant.

Implements the ReAct-style dynamic tool-calling loop (Reason -> Act -> Observe)
with explicit step budgets, loop detection, and structured trajectory logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from epr_agent.agent.agent_prompt import SYSTEM_PROMPT
from epr_agent.agent.planner import AgentBudgetController
from epr_agent.agent.tool_registry import ALL_AGENT_TOOLS
from epr_agent.domain.models import TerminationReason

logger = logging.getLogger(__name__)


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
    awaiting_user_input: bool = False
    follow_up_question: str = ""
    case_state: dict[str, Any] | None = None
    assessment: dict[str, Any] | None = None
    task_type: str = "legal_lookup"
    route: str = "legal_lookup"


@dataclass
class AgentRunConfig:
    """Configuration and guardrail limits for the agent loop."""

    max_steps: int = 5
    max_search_calls: int = 4
    max_web_calls: int = 1
    tool_timeout_s: float = 20.0
    enable_cache: bool = True


class EprAgentRunner:
    """Autonomous ReAct runner for Vietnamese EPR legal analysis."""

    def __init__(
        self,
        config: AgentRunConfig | None = None,
        llm: Any | None = None,
        tools: list[Any] | None = None,
    ) -> None:
        self.config = config or AgentRunConfig()
        self.tools = tools or ALL_AGENT_TOOLS
        self._tools_map = {t.__name__: t for t in self.tools}

        if llm is not None:
            self._llm = llm
        else:
            from backend.core.llm_instances import get_llm_router

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
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute the agent loop, streaming step status events and final result."""
        trajectory: list[AgentStep] = []
        all_evidence: list[dict[str, Any]] = []
        cache_hit = False
        assessment_payload: dict[str, Any] | None = None

        messages = self._build_initial_messages(
            query,
            history=history or [],
            active_case=active_case,
            history_summary=history_summary,
            mode=mode,
        )

        step = 0
        for step in range(self.config.max_steps):
            if not self._budget.within_step_budget(step):
                break

            # ── 1. REASON: Call LLM to deliberate and choose action ──
            try:
                response = await self._llm.ainvoke(messages)
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
                        citations=[],
                        source="cache" if cache_hit else "legal",
                        steps_taken=step + 1,
                        cache_hit=cache_hit,
                        assessment=assessment_payload,
                    ),
                }
                return

            # ── 3. ACT & OBSERVE: Execute each tool requested by LLM ──
            for tool_call in tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {}) or {}
                call_id = tool_call.get("id", f"call_{step}_{tool_name}")

                yield {
                    "type": "agent_tool_call",
                    "step": step + 1,
                    "tool": tool_name,
                    "args": tool_args,
                    "trace_id": trace_id,
                }

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
                    continue

                # Execute the tool
                started = time.perf_counter()
                observation = await self._execute_tool(tool_name, tool_args)
                latency_ms = round((time.perf_counter() - started) * 1000, 2)

                # Track evidence
                if "documents" in observation and isinstance(observation["documents"], list):
                    all_evidence.extend(observation["documents"])

                # Track cache
                if tool_name == "lookup_answer_cache" and observation.get("hit"):
                    cache_hit = True

                # Track assessment results
                if tool_name == "evaluate_epr_obligation" and observation.get("ok"):
                    assessment_payload = observation

                # Handle terminal clarification action
                if tool_name == "ask_user_for_clarification" or observation.get("awaiting_user_input"):
                    question = observation.get("question") or "Bạn có thể cung cấp thêm thông tin cần thiết không?"
                    yield {
                        "type": "agent_complete",
                        "result": AgentRunResult(
                            answer=question,
                            termination_reason=TerminationReason.AWAITING_USER_INPUT.value,
                            trajectory=trajectory,
                            evidence=[],
                            citations=[],
                            source="follow_up",
                            steps_taken=step + 1,
                            cache_hit=False,
                            awaiting_user_input=True,
                            follow_up_question=question,
                            case_state={
                                "status": "collecting",
                                "missing_facts": observation.get("missing_fields", []),
                            },
                        ),
                    }
                    return

                # Append tool observation to message scratchpad
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": (
                        json.dumps(observation, ensure_ascii=False)
                        if isinstance(observation, dict)
                        else str(observation)
                    ),
                })

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

        # ── 4. MAX STEPS REACHED: Safe termination fallback ──
        yield {
            "type": "agent_complete",
            "result": AgentRunResult(
                answer="Tôi chưa thể tìm đủ căn cứ pháp lý để đưa ra kết luận an toàn sau các bước tra cứu.",
                termination_reason=TerminationReason.INSUFFICIENT_EVIDENCE.value,
                trajectory=trajectory,
                evidence=all_evidence,
                citations=[],
                source="error",
                steps_taken=step + 1,
                cache_hit=False,
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
    ) -> list[Any]:
        messages: list[Any] = [("system", SYSTEM_PROMPT)]
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
        except TimeoutError:
            return {"error": f"Tool '{name}' timed out after {self.config.tool_timeout_s}s", "ok": False}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}", "ok": False}
