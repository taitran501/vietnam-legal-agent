from __future__ import annotations

from copy import deepcopy

from epr_agent.domain.epr_rules import CaseFormResolver
from epr_agent.domain.v4 import FactSource, FactValue


def _facts(**values: str) -> dict[str, FactValue]:
    return {
        key: FactValue(value=value, source=FactSource.CASE_PANEL, confirmation_status="user_confirmed")
        for key, value in values.items()
    }


def test_resolver_exposes_base_fields_and_dynamic_counts_without_mutating_input():
    original = _facts(business_role="manufacturer")
    before = deepcopy(original)

    state = CaseFormResolver().resolve("assess_epr_obligation", original)

    assert state.form_version == "case-form-v1"
    assert state.status == "collecting"
    assert state.completed_count == 1
    assert state.required_count == 5
    assert "object_kind" in state.missing_facts
    assert original == before


def test_packaging_and_reuse_dependencies_appear_after_parent_values():
    resolver = CaseFormResolver()
    domestic = resolver.resolve(
        "assess_epr_obligation",
        fact_updates={
            "business_role": {"value": "manufacturer", "confirmation_status": "user_confirmed"},
            "object_kind": {"value": "commercial_packaging", "confirmation_status": "user_confirmed"},
            "product_group": {"value": "bao_bi", "confirmation_status": "user_confirmed"},
            "market_placement": {"value": "vietnam_market", "confirmation_status": "user_confirmed"},
            "activity_purpose": {"value": "commercial", "confirmation_status": "user_confirmed"},
        },
    )

    keys = {field.key for field in domestic.fields}
    assert {"packaged_goods_category", "annual_revenue_vnd", "reused_by_producer"} <= keys
    assert "recovery_rate" not in keys
    assert domestic.missing_facts == ["packaged_goods_category", "annual_revenue_vnd", "reused_by_producer"]

    reused = resolver.resolve(
        domestic.task_type,
        domestic.facts,
        {"reused_by_producer": {"value": "yes", "confirmation_status": "user_confirmed"}},
    )
    assert "recovery_rate" in {field.key for field in reused.fields}
    assert "recovery_rate" in reused.missing_facts


def test_invalid_numeric_values_are_structured_errors_not_empty_facts():
    state = CaseFormResolver().resolve(
        "assess_epr_obligation",
        fact_updates={
            "annual_revenue_vnd": {"value": "29999999999.5", "confirmation_status": "user_confirmed"},
            "recovery_rate": {"value": "101", "confirmation_status": "user_confirmed"},
        },
    )

    assert set(state.validation_errors) == {"annual_revenue_vnd", "recovery_rate"}
    assert "annual_revenue_vnd" not in state.facts
    assert "recovery_rate" not in state.facts


def test_empty_update_is_an_explicit_delete():
    state = CaseFormResolver().resolve(
        "assess_epr_obligation",
        _facts(business_role="manufacturer"),
        {"business_role": {"value": "", "confirmation_status": "user_confirmed"}},
    )

    assert "business_role" not in state.facts
    assert "business_role" in state.missing_facts


def test_unknown_fact_update_is_rejected_without_polluting_form_state():
    state = CaseFormResolver().resolve(
        "assess_epr_obligation",
        fact_updates={"internal_debug_flag": {"value": "true", "confirmation_status": "unknown"}},
    )

    assert state.facts == {}
    assert state.validation_errors == {
        "internal_debug_flag": "Thông tin này không thuộc biểu mẫu EPR hiện tại."
    }
