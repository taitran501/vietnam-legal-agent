"""Side-effect-free guided case-form resolution."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import CaseFormResolveRequest
from epr_agent.domain.epr_rules import CaseFormResolver
from epr_agent.domain.v4 import CaseFormState

router = APIRouter()
_resolver = CaseFormResolver()


@router.post("/case-form/resolve", response_model=CaseFormState, tags=["case"])
async def resolve_case_form(body: CaseFormResolveRequest):
    """Resolve visible fields and validation without creating a conversation."""

    state = _resolver.resolve(
        body.task_type,
        fact_updates={key: update.model_dump(mode="json") for key, update in body.fact_updates.items()},
    )
    return state.model_dump(mode="json")
