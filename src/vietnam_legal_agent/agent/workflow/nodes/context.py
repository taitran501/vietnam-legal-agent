from __future__ import annotations

from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.agent.workflow.contracts import WorkflowDependencies


class WorkflowNodeContext:
    """Shared injected dependencies for bounded workflow node handlers."""

    def __init__(self, deps: WorkflowDependencies) -> None:
        self.deps = deps
        self.planner: BoundedPlanner = deps.planner
