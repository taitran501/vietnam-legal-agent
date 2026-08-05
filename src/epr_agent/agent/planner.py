"""Bounded transition policy for the EPR workflow.

There is no free-form tool call here.  The planner returns one member of
``Action`` and the graph owns the actual transition.  This is the important
boundary between an agentic workflow and an unconstrained chatbot loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from epr_agent.domain.models import Action, AgentState, TaskType


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    action: Action
    reason: str


class BoundedPlanner:
    """Choose only safe, known actions with explicit budgets."""

    def __init__(self, *, max_retrieval_actions: int = 3, max_repairs: int = 1, max_iterations: int = 12) -> None:
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
        task = TaskType(state.get("task_type", TaskType.LEGAL_LOOKUP.value))
        if task == TaskType.CHITCHAT:
            return PlannerDecision(Action.COMPOSE_ANSWER, "greeting_or_small_talk")
        if state.get("missing_facts"):
            return PlannerDecision(Action.ASK_USER, "required_case_facts_missing")
        return PlannerDecision(Action.CHECK_CACHE, "task_is_ready_for_retrieval")

    def after_cache(self, state: AgentState) -> PlannerDecision:
        if state.get("cached_answer"):
            return PlannerDecision(Action.ANSWER_CACHE, "scoped_legal_lookup_cache_hit")
        return PlannerDecision(Action.RETRIEVE_FAQ, "cache_miss_or_cache_not_allowed")

    def after_faq(self, state: AgentState) -> PlannerDecision:
        if state.get("evidence"):
            return PlannerDecision(Action.COMPOSE_ANSWER, "faq_match_found")
        if self.can_retrieve(state):
            return PlannerDecision(Action.RETRIEVE_LEGAL, "faq_miss")
        return PlannerDecision(Action.SAFE_STOP, "retrieval_budget_exhausted")

    def after_evidence(self, state: AgentState) -> PlannerDecision:
        assessment = state.get("evidence_assessment") or {}
        if assessment.get("sufficient"):
            return PlannerDecision(Action.COMPOSE_ANSWER, "evidence_sufficient")
        if state.get("is_epr_scope") and self.can_retrieve(state):
            return PlannerDecision(Action.RETRIEVE_WEB, "corpus_evidence_insufficient_but_scope_is_epr")
        return PlannerDecision(Action.SAFE_STOP, "evidence_insufficient_or_out_of_scope")

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
