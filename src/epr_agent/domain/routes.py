"""Route contracts for the bounded legal workflow.

Routes own product behaviour while all legal routes share the same retrieval
and evidence core.  ``task_type`` remains a compatibility field for the
existing API and React workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from epr_agent.domain.models import TaskType


class RouteType(StrEnum):
    CHITCHAT = "chitchat"
    LEGAL_LOOKUP = "legal_lookup"
    LEGAL_EXPLAIN_COMPARE = "legal_explain_compare"
    CASE_ASSESSMENT = "case_assessment"
    COMPLIANCE_CHECKLIST = "compliance_checklist"
    RESEARCH_WEB = "research_web"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True, slots=True)
class RouteSpec:
    route: RouteType
    task_type: TaskType
    max_evidence: int
    cacheable: bool
    requires_case_facts: bool = False
    source_scope: str = "legal_corpus"


ROUTE_SPECS: dict[RouteType, RouteSpec] = {
    RouteType.CHITCHAT: RouteSpec(RouteType.CHITCHAT, TaskType.CHITCHAT, 0, False, source_scope="none"),
    RouteType.LEGAL_LOOKUP: RouteSpec(RouteType.LEGAL_LOOKUP, TaskType.LEGAL_LOOKUP, 3, True),
    RouteType.LEGAL_EXPLAIN_COMPARE: RouteSpec(RouteType.LEGAL_EXPLAIN_COMPARE, TaskType.LEGAL_LOOKUP, 6, False),
    RouteType.CASE_ASSESSMENT: RouteSpec(
        RouteType.CASE_ASSESSMENT,
        TaskType.CASE_ASSESSMENT,
        5,
        False,
        requires_case_facts=True,
    ),
    RouteType.COMPLIANCE_CHECKLIST: RouteSpec(
        RouteType.COMPLIANCE_CHECKLIST,
        TaskType.BUILD_COMPLIANCE_CHECKLIST,
        5,
        False,
        requires_case_facts=True,
    ),
    RouteType.RESEARCH_WEB: RouteSpec(RouteType.RESEARCH_WEB, TaskType.LEGAL_LOOKUP, 5, False, source_scope="web_research"),
    RouteType.OUT_OF_SCOPE: RouteSpec(RouteType.OUT_OF_SCOPE, TaskType.LEGAL_LOOKUP, 0, False, source_scope="none"),
}


def route_spec(value: RouteType | str) -> RouteSpec:
    return ROUTE_SPECS[RouteType(value)]


def route_for_task(task: TaskType) -> RouteType:
    if task == TaskType.CASE_ASSESSMENT:
        return RouteType.CASE_ASSESSMENT
    if task == TaskType.BUILD_COMPLIANCE_CHECKLIST:
        return RouteType.COMPLIANCE_CHECKLIST
    if task == TaskType.CHITCHAT:
        return RouteType.CHITCHAT
    return RouteType.LEGAL_LOOKUP
