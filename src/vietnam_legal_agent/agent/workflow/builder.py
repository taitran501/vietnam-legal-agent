from __future__ import annotations

from langgraph.graph import END, StateGraph

from vietnam_legal_agent.agent.workflow.contracts import WorkflowDependencies
from vietnam_legal_agent.agent.workflow.nodes.answer import AnswerNodeHandlers
from vietnam_legal_agent.agent.workflow.nodes.intake import IntakeNodeHandlers
from vietnam_legal_agent.agent.workflow.nodes.retrieval import RetrievalNodeHandlers
from vietnam_legal_agent.agent.workflow.nodes.verification import VerificationNodeHandlers
from vietnam_legal_agent.domain.models import AgentState, TaskType


def build_workflow(deps: WorkflowDependencies):
    """Wire the bounded workflow; stage behavior lives in injected node handlers."""
    intake = IntakeNodeHandlers(deps)
    retrieval = RetrievalNodeHandlers(deps)
    answer = AnswerNodeHandlers(deps)
    verification = VerificationNodeHandlers(deps)
    graph = StateGraph(AgentState)

    graph.add_node("validate_input", intake.validate_input)
    graph.add_node("load_context", intake.load_context)
    graph.add_node("understand_task", intake.understand_task)
    graph.add_node("check_cache", intake.check_cache)
    graph.add_node("ask_user", intake.ask_user)
    graph.add_node("answer_cache", intake.answer_cache)
    graph.add_node("retrieve_legal", retrieval.retrieve_legal)
    graph.add_node("evaluate_evidence", retrieval.evaluate_evidence)
    graph.add_node("retrieve_web", retrieval.retrieve_web)
    graph.add_node("compose", answer.compose_answer)
    graph.add_node("verify", verification.verify)
    graph.add_node("repair", answer.repair_answer)
    graph.add_node("finish", answer.finish)
    graph.add_node("safe_stop", verification.safe_stop)

    graph.set_entry_point("validate_input")
    graph.add_conditional_edges(
        "validate_input",
        lambda state: "safe_stop" if state.get("error") else "load_context",
        {"safe_stop": "safe_stop", "load_context": "load_context"},
    )
    graph.add_edge("load_context", "understand_task")
    graph.add_conditional_edges(
        "understand_task",
        intake.route_after_understanding,
        {
            "compose": "compose",
            "ask_user": "ask_user",
            "retrieve_web": "retrieve_web",
            "safe_stop": "safe_stop",
            "cache": "check_cache",
        },
    )
    graph.add_conditional_edges(
        "check_cache",
        intake.route_after_cache,
        {"answer_cache": "answer_cache", "retrieve_legal": "retrieve_legal"},
    )
    graph.add_edge("ask_user", END)
    # Cache hits are candidates, not trusted final answers; verify them normally.
    graph.add_edge("answer_cache", "verify")
    graph.add_edge("retrieve_legal", "evaluate_evidence")
    graph.add_conditional_edges(
        "evaluate_evidence",
        retrieval.route_after_evidence,
        {"compose": "compose", "safe_stop": "safe_stop"},
    )
    graph.add_conditional_edges(
        "retrieve_web",
        retrieval.route_after_web,
        {"compose": "compose", "safe_stop": "safe_stop"},
    )
    graph.add_conditional_edges(
        "compose",
        lambda state: "finish" if state.get("task_type") == TaskType.CHITCHAT.value else "verify",
        {"finish": "finish", "verify": "verify"},
    )
    graph.add_conditional_edges(
        "verify",
        verification.route_after_verify,
        {"finish": "finish", "repair": "repair", "safe_stop": "safe_stop"},
    )
    graph.add_edge("repair", "verify")
    graph.add_edge("finish", END)
    graph.add_edge("safe_stop", END)
    return graph.compile()
