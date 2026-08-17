from epr_agent.agent.planner import AgentBudgetController, BoundedPlanner
from epr_agent.domain.models import Action


def test_planner_has_closed_action_surface_and_budgets():
    planner = BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12)
    state = {"retrieval_actions": 3, "repair_count": 1, "iteration": 12}
    assert planner.can_retrieve(state) is False
    assert planner.can_repair(state) is False
    assert planner.within_iteration_budget(state) is False
    assert planner.validate(Action.RETRIEVE_LEGAL) == Action.RETRIEVE_LEGAL


def test_agent_budget_controller_step_budget():
    controller = AgentBudgetController(max_steps=5)
    assert controller.within_step_budget(0) is True
    assert controller.within_step_budget(4) is True
    assert controller.within_step_budget(5) is False


def test_agent_budget_controller_loop_detection():
    controller = AgentBudgetController(max_steps=5)
    trajectory = [
        {"tool": "search_legal_provisions", "args": {"query": "Điều 77"}},
    ]
    # Calling identical tool + args -> denied
    check = controller.check_tool_call(
        "search_legal_provisions",
        {"query": "Điều 77"},
        trajectory,
    )
    assert check.allowed is False
    assert "loop_detected" in check.reason

    # Calling with different args -> allowed
    check2 = controller.check_tool_call(
        "search_legal_provisions",
        {"query": "Điều 54 Nghị định 08"},
        trajectory,
    )
    assert check2.allowed is True


def test_agent_budget_controller_search_budget():
    controller = AgentBudgetController(max_search_calls=2)
    trajectory = [
        {"tool": "search_legal_provisions", "args": {"query": "Điều 77"}},
        {"tool": "search_legal_provisions", "args": {"query": "Điều 54"}},
    ]
    check = controller.check_tool_call(
        "search_legal_provisions",
        {"query": "Điều 55"},
        trajectory,
    )
    assert check.allowed is False
    assert "search_budget_exceeded" in check.reason


def test_agent_budget_controller_web_budget():
    controller = AgentBudgetController(max_web_calls=1)
    trajectory = [
        {"tool": "search_web_official", "args": {"query": "Luật 2024"}},
    ]
    check = controller.check_tool_call(
        "search_web_official",
        {"query": "Nghị định mới"},
        trajectory,
    )
    assert check.allowed is False
    assert "web_budget_exceeded" in check.reason
