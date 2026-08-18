"""Document upload, parsing, contract redlining, and DOCX export routes."""

from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from epr_agent.tools.document_parser import parse_document_file
from epr_agent.tools.contract_redliner import review_contract_clauses_heuristic, review_contract_with_llm
from epr_agent.tools.document_drafter import (
    CourtPetitionPayload,
    draft_court_petition_form_23,
    draft_safe_deposit_agreement,
    generate_docx_bytes,
)
from epr_agent.tools.legal_calculators import (
    calculate_court_fees,
    calculate_illegal_termination_compensation,
    calculate_land_transfer_taxes,
    calculate_overdue_interest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


class ExportDocxRequest(BaseModel):
    title: str = Field(default="Van_ban_phap_ly", description="Tiêu đề văn bản")
    content: str = Field(description="Nội dung văn bản định dạng text")


class CalculateCourtFeeRequest(BaseModel):
    claim_amount: float = Field(default=0.0)
    dispute_type: str = Field(default="dân sự")
    has_monetary_value: bool = Field(default=True)


class CalculateSeveranceRequest(BaseModel):
    monthly_salary: float
    months_worked: float = 12.0
    unemployed_months: float = 2.0
    days_without_notice: int = 0
    has_unemployment_insurance: bool = True


class CalculateInterestRequest(BaseModel):
    principal_amount: float
    days_overdue: int
    agreed_annual_rate: float = 10.0
    is_commercial_contract: bool = False


class CalculateLandTaxRequest(BaseModel):
    property_value: float
    is_first_and_only_home: bool = False
    is_direct_family_transfer: bool = False


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    analyze_redline: bool = Form(default=True),
) -> dict[str, Any]:
    """Upload and parse contract or legal instrument (PDF, DOCX, TXT)."""
    try:
        content_bytes = await file.read()
        if not content_bytes:
            raise HTTPException(status_code=400, detail="File tải lên không có dữ liệu (rỗng)")

        parsed = parse_document_file(
            content_bytes=content_bytes,
            filename=file.filename or "uploaded_document.pdf",
            mime_type=file.content_type or "application/pdf",
        )

        redline_report = None
        if analyze_redline and parsed.clauses:
            try:
                redline_report = await review_contract_with_llm(
                    clauses=parsed.clauses,
                    document_title=file.filename or "Hợp đồng",
                )
            except Exception as exc:
                logger.warning("LLM redline failed; falling back to heuristic: %s", exc)
                redline_report = review_contract_clauses_heuristic(
                    clauses=parsed.clauses,
                    document_title=file.filename or "Hợp đồng",
                )

        return {
            "status": "success",
            "document": parsed.model_dump(mode="json"),
            "redline_report": redline_report.model_dump(mode="json") if redline_report else None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Document upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Không thể xử lý tài liệu: {exc}") from exc


@router.post("/export-docx")
async def export_docx(payload: ExportDocxRequest):
    """Generate and return authentic .docx file adhering to Decree 30/2020/ND-CP."""
    try:
        docx_bytes = generate_docx_bytes(title=payload.title, content=payload.content)
        clean_name = payload.title.strip().replace(" ", "_").lower()
        if not clean_name.endswith(".docx"):
            clean_name = f"{clean_name}.docx"

        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{clean_name}"'},
        )
    except Exception as exc:
        logger.error("DOCX export failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Không thể xuất file Word: {exc}") from exc


@router.post("/draft/court-petition")
async def draft_court_petition(payload: CourtPetitionPayload):
    """Draft official Court Petition (Mẫu số 23-DS TANDTC)."""
    result = draft_court_petition_form_23(payload)
    return result.model_dump(mode="json")


@router.post("/draft/deposit-contract")
async def draft_deposit(
    buyer_name: str = "Bên A (Bên mua)",
    seller_name: str = "Bên B (Bên bán)",
    property_address: str = "Thửa đất số ..., Tờ bản đồ số ..., Địa chỉ: ...",
    deposit_amount: float = 100000000.0,
    total_price: float = 2000000000.0,
    signing_deadline_days: int = 30,
):
    """Draft safe Real Estate Deposit Agreement."""
    result = draft_safe_deposit_agreement(
        buyer_name=buyer_name,
        seller_name=seller_name,
        property_address=property_address,
        deposit_amount=deposit_amount,
        total_price=total_price,
        signing_deadline_days=signing_deadline_days,
    )
    return result.model_dump(mode="json")


@router.post("/calculate/court-fee")
async def calc_court_fee(payload: CalculateCourtFeeRequest):
    """Calculate Court Legal Fees under Resolution 326/2016/UBTVQH14."""
    result = calculate_court_fees(
        claim_amount=payload.claim_amount,
        dispute_type=payload.dispute_type,
        has_monetary_value=payload.has_monetary_value,
    )
    return result.model_dump(mode="json")


@router.post("/calculate/severance")
async def calc_severance(payload: CalculateSeveranceRequest):
    """Calculate illegal dismissal compensation under Labor Code 2019."""
    result = calculate_illegal_termination_compensation(
        monthly_salary=payload.monthly_salary,
        months_worked=payload.months_worked,
        unemployed_months=payload.unemployed_months,
        days_without_notice=payload.days_without_notice,
        has_unemployment_insurance=payload.has_unemployment_insurance,
    )
    return result.model_dump(mode="json")


@router.post("/calculate/interest")
async def calc_interest(payload: CalculateInterestRequest):
    """Calculate overdue interest with Civil Code 2015 statutory cap."""
    result = calculate_overdue_interest(
        principal_amount=payload.principal_amount,
        days_overdue=payload.days_overdue,
        agreed_annual_rate=payload.agreed_annual_rate,
        is_commercial_contract=payload.is_commercial_contract,
    )
    return result.model_dump(mode="json")


@router.post("/calculate/land-tax")
async def calc_land_tax(payload: CalculateLandTaxRequest):
    """Calculate Real Estate Transfer PIT (2%) and Registration Fee (0.5%)."""
    result = calculate_land_transfer_taxes(
        property_value=payload.property_value,
        is_first_and_only_home=payload.is_first_and_only_home,
        is_direct_family_transfer=payload.is_direct_family_transfer,
    )
    return result.model_dump(mode="json")
