"""Bounded transition policy for the EPR workflow.

There is no free-form tool call here.  The planner returns one member of
``Action`` and the graph owns the actual transition.  This is the important
boundary between an agentic workflow and an unconstrained chatbot loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from epr_agent.domain.models import Action, AgentState
from epr_agent.domain.routes import RouteType


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    action: Action
    reason: str


class BoundedPlanner:
    """Choose only safe, known actions with explicit budgets."""

    def __init__(self, *, max_retrieval_actions: int = 2, max_repairs: int = 1, max_iterations: int = 12) -> None:
        self.max_retrieval_actions = max_retrieval_actions
        self.max_repairs = max_repairs
        self.max_iterations = max_iterations

    def can_retrieve(self, state: AgentState) -> bool:
        return int(state.get("retrieval_actions", 0)) < self.max_retrieval_actions

    def can_repair(self, state: AgentState) -> bool:
        return int(state.get("repair_count", 0)) < self.max_repairs

    def within_iteration_budget(self, state: AgentState) -> bool:
        return int(state.get("iteration", 0)) < self.max_iterations

    def after_understanding(self, state: AgentState) -> PlannerDecision:
        route = RouteType(state.get("route", RouteType.LEGAL_LOOKUP.value))
        if route == RouteType.CHITCHAT:
            return PlannerDecision(Action.COMPOSE_ANSWER, "greeting_or_small_talk")
        if route == RouteType.OUT_OF_SCOPE:
            return PlannerDecision(Action.SAFE_STOP, "outside_registered_corpus")
        if route == RouteType.RESEARCH_WEB:
            return PlannerDecision(Action.RETRIEVE_WEB, "user_selected_research_web")
        if state.get("clarification_required"):
            return PlannerDecision(Action.ASK_USER, "route_confidence_below_calibrated_threshold")
        if state.get("missing_facts"):
            return PlannerDecision(Action.ASK_USER, "required_case_facts_missing")
        return PlannerDecision(Action.CHECK_CACHE, "task_is_ready_for_retrieval")

    def after_cache(self, state: AgentState) -> PlannerDecision:
        if state.get("cached_answer"):
            return PlannerDecision(Action.ANSWER_CACHE, "scoped_legal_lookup_cache_hit")
        return PlannerDecision(Action.RETRIEVE_LEGAL, "cache_miss_or_cache_not_allowed")

    def after_evidence(self, state: AgentState) -> PlannerDecision:
        assessment = state.get("evidence_assessment") or {}
        if assessment.get("sufficient"):
            return PlannerDecision(Action.COMPOSE_ANSWER, "evidence_sufficient")
        return PlannerDecision(Action.SAFE_STOP, "corpus_evidence_insufficient")

    def after_verification(self, state: AgentState) -> PlannerDecision:
        if state.get("citation_valid"):
            return PlannerDecision(Action.FINISH, "citations_verified")
        if self.can_repair(state):
            return PlannerDecision(Action.REPAIR_ANSWER, "citation_verification_failed_once")
        return PlannerDecision(Action.SAFE_STOP, "citation_verification_failed_after_repair")

    def validate(self, action: Action) -> Action:
        """Keep the action surface closed if a model-backed planner is added."""

        if not isinstance(action, Action):
            raise TypeError(f"Unknown planner action: {action!r}")
        return action


@dataclass(frozen=True, slots=True)
class BudgetCheckResult:
    allowed: bool
    reason: str


class AgentBudgetController:
    """Enforces safety budgets, tool call limits, and loop detection for autonomous agent."""

    def __init__(
        self,
        *,
        max_steps: int = 5,
        max_search_calls: int = 4,
        max_web_calls: int = 1,
    ) -> None:
        self.max_steps = max(1, max_steps)
        self.max_search_calls = max(1, max_search_calls)
        self.max_web_calls = max(0, max_web_calls)

    def check_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        trajectory: list[dict[str, Any]],
    ) -> BudgetCheckResult:
        """Check if a tool call is permitted before execution."""
        # 1. Loop detection: prevent calling the exact same tool with identical args
        for prev in trajectory:
            if prev.get("tool") == tool_name and prev.get("args") == tool_args:
                return BudgetCheckResult(
                    allowed=False,
                    reason=f"loop_detected: Tool '{tool_name}' already called with identical arguments.",
                )

        # 2. Search calls budget (legal + web)
        if tool_name in {"search_legal_provisions", "search_web_official"}:
            search_count = sum(
                1 for t in trajectory if t.get("tool") in {"search_legal_provisions", "search_web_official"}
            )
            if search_count >= self.max_search_calls:
                return BudgetCheckResult(
                    allowed=False,
                    reason=f"search_budget_exceeded: Reached maximum search calls limit ({self.max_search_calls}).",
                )

        # 3. Web search budget
        if tool_name == "search_web_official":
            web_count = sum(1 for t in trajectory if t.get("tool") == "search_web_official")
            if web_count >= self.max_web_calls:
                return BudgetCheckResult(
                    allowed=False,
                    reason=f"web_budget_exceeded: Reached maximum web calls limit ({self.max_web_calls}).",
                )

        return BudgetCheckResult(allowed=True, reason="ok")

    def within_step_budget(self, current_step: int) -> bool:
        return current_step < self.max_steps

