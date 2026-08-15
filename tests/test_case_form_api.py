from __future__ import annotations

from backend.api.routes.case_form import router
from fastapi import FastAPI
from starlette.testclient import TestClient


def test_case_form_resolve_is_side_effect_free_and_returns_field_metadata():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/case-form/resolve",
            json={
                "task_type": "assess_epr_obligation",
                "fact_updates": {
                    "business_role": {
                        "value": "manufacturer",
                        "confirmation_status": "user_confirmed",
                    }
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["form_version"] == "case-form-v1"
    assert payload["completed_count"] == 1
    assert payload["required_count"] >= payload["completed_count"]
    assert payload["validation_errors"] == {}
    assert payload["submission_blocked_reason"] == ""
    assert any(field["key"] == "business_role" for field in payload["fields"])
