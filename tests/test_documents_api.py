"""API-level tests for documents upload, export, draft, and calculate endpoints."""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from backend.api.routes.documents import router
from fastapi import FastAPI
from starlette.testclient import TestClient


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1")
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Upload tests ────────────────────────────────────────────────────────────


class TestUploadDocument:
    """Tests for POST /api/v1/documents/upload."""

    def test_upload_valid_txt(self, client: TestClient):
        content = b"Dieu 1: Pham vi ap dung. Hop dong nay ap dung cho cac ben."
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("contract.txt", io.BytesIO(content), "text/plain")},
            data={"analyze_redline": "false"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["document"]["file_type"] == "txt"
        assert "Dieu 1" in body["document"]["raw_text"]

    def test_upload_empty_file(self, client: TestClient):
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_oversized_file(self, client: TestClient):
        large_content = b"x" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("big.txt", io.BytesIO(large_content), "text/plain")},
        )
        assert resp.status_code == 413
        assert "10 MB" in resp.json()["detail"]

    def test_upload_wrong_mime_type(self, client: TestClient):
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("script.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        )
        assert resp.status_code == 415
        assert "Unsupported file type" in resp.json()["detail"]

    @patch("backend.api.routes.documents.parse_document_file")
    def test_upload_valid_pdf(self, mock_parse, client: TestClient):
        from epr_agent.tools.document_parser import DocumentParseResult

        mock_parse.return_value = DocumentParseResult(
            document_id="doc-1",
            filename="contract.pdf",
            file_type="pdf",
            total_chars=100,
            raw_text="Hop dong lao dong",
            clauses=[],
        )
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("contract.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            data={"analyze_redline": "false"},
        )
        assert resp.status_code == 200
        assert resp.json()["document"]["file_type"] == "pdf"
        mock_parse.assert_called_once()

    def test_upload_no_redline(self, client: TestClient):
        content = b"Noi dung hop dong don gian."
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("simple.txt", io.BytesIO(content), "text/plain")},
            data={"analyze_redline": "false"},
        )
        assert resp.status_code == 200
        assert resp.json()["redline_report"] is None


# ── Export tests ────────────────────────────────────────────────────────────


class TestExportDocx:
    """Tests for POST /api/v1/documents/export-docx."""

    @patch("backend.api.routes.documents.generate_docx_bytes")
    def test_export_docx_valid(self, mock_gen, client: TestClient):
        mock_gen.return_value = b"fake-docx-bytes"
        resp = client.post(
            "/api/v1/documents/export-docx",
            json={"title": "Hop dong", "content": "Noi dung van ban"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert resp.content == b"fake-docx-bytes"

    @patch("backend.api.routes.documents.generate_docx_bytes")
    def test_export_docx_vietnamese_title(self, mock_gen, client: TestClient):
        mock_gen.return_value = b"fake-docx-bytes"
        resp = client.post(
            "/api/v1/documents/export-docx",
            json={"title": "H\u1ee3p \u0111\u1ed3ng \u0111\u1eb7t c\u1ecdc", "content": "Noi dung"},
        )
        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        # RFC 5987: should contain UTF-8 encoded Vietnamese filename
        assert "filename*=UTF-8''" in disposition
        # ASCII fallback should also be present
        assert 'filename="' in disposition

    @patch("backend.api.routes.documents.generate_docx_bytes")
    def test_export_docx_title_injection(self, mock_gen, client: TestClient):
        mock_gen.return_value = b"fake-docx-bytes"
        resp = client.post(
            "/api/v1/documents/export-docx",
            json={"title": 'foo"; rm -rf /', "content": "Noi dung"},
        )
        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        # Double-quote should be stripped, not injected into header
        assert '"; rm -rf /' not in disposition


# ── Draft tests ─────────────────────────────────────────────────────────────


class TestDraftEndpoints:
    """Tests for POST /api/v1/documents/draft/* endpoints."""

    def test_draft_court_petition(self, client: TestClient):
        resp = client.post(
            "/api/v1/documents/draft/court-petition",
            json={
                "plaintiff_name": "Nguyen Van A",
                "defendant_name": "Tran Thi B",
                "court_name": "TAND quan 1",
                "case_summary": "Tranh chap hop dong dat coc",
                "legal_basis_and_violations": "Dieu 127 BLDS 2015",
                "petition_requests": ["Buoc phuc loi", "Boi thuong 100 trieu"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["document_type"] == "court_petition"
        assert "Nguyen Van A" in body["plain_text"]
        assert body["legal_basis"]  # non-empty

    def test_draft_deposit_contract(self, client: TestClient):
        resp = client.post("/api/v1/documents/draft/deposit-contract")
        assert resp.status_code == 200
        body = resp.json()
        assert body["document_type"] == "deposit_contract"
        assert "B\u00ean A" in body["plain_text"]


# ── Calculator tests ────────────────────────────────────────────────────────


class TestCalculators:
    """Tests for POST /api/v1/documents/calculate/* endpoints."""

    def test_calc_court_fee(self, client: TestClient):
        resp = client.post(
            "/api/v1/documents/calculate/court-fee",
            json={"claim_amount": 500_000_000, "dispute_type": "d\u00e2n s\u1ef1", "has_monetary_value": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "first_instance_fee" in body
        assert body["first_instance_fee"] > 0

    def test_calc_severance(self, client: TestClient):
        resp = client.post(
            "/api/v1/documents/calculate/severance",
            json={
                "monthly_salary": 15_000_000,
                "months_worked": 24,
                "unemployed_months": 3,
                "days_without_notice": 0,
                "has_unemployment_insurance": True,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "total_compensation" in body
        assert body["total_compensation"] > 0

    def test_calc_interest(self, client: TestClient):
        resp = client.post(
            "/api/v1/documents/calculate/interest",
            json={
                "principal_amount": 1_000_000_000,
                "days_overdue": 90,
                "agreed_annual_rate": 10.0,
                "is_commercial_contract": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "total_interest" in body
        assert body["total_interest"] > 0

    def test_calc_interest_commercial(self, client: TestClient):
        resp = client.post(
            "/api/v1/documents/calculate/interest",
            json={
                "principal_amount": 1_000_000_000,
                "days_overdue": 90,
                "agreed_annual_rate": 12.0,
                "is_commercial_contract": True,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_interest"] > 0

    def test_calc_land_tax(self, client: TestClient):
        resp = client.post(
            "/api/v1/documents/calculate/land-tax",
            json={
                "property_value": 3_000_000_000,
                "is_first_and_only_home": False,
                "is_direct_family_transfer": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "registration_fee" in body
        assert "personal_income_tax" in body
        assert body["registration_fee"] > 0

    def test_calc_land_tax_first_home(self, client: TestClient):
        resp = client.post(
            "/api/v1/documents/calculate/land-tax",
            json={
                "property_value": 3_000_000_000,
                "is_first_and_only_home": True,
                "is_direct_family_transfer": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # First home should reduce PIT
        assert body["personal_income_tax"] >= 0
