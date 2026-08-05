from epr_agent.agent.planner import BoundedPlanner
from epr_agent.domain.models import Action


def test_planner_has_closed_action_surface_and_budgets():
    planner = BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12)
    state = {"retrieval_actions": 3, "repair_count": 1, "iteration": 12}
    assert planner.can_retrieve(state) is False
    assert planner.can_repair(state) is False
    assert planner.within_iteration_budget(state) is False
    assert planner.validate(Action.RETRIEVE_LEGAL) == Action.RETRIEVE_LEGAL
