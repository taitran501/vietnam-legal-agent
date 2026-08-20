"""High-precision legal calculators engine for Vietnamese statutory formulas.

Formulas implemented:
1. Court Legal Fees (Án phí Tòa án Dân sự / Kinh doanh Thương mại / Lao động):
   Nghị quyết 326/2016/UBTVQH14 của Ủy ban Thường vụ Quốc hội.
2. Illegal Termination & Severance Compensation (Bồi thường sa thải & thôi việc):
   Điều 41, Điều 46, Điều 47 Bộ luật Lao động số 45/2019/QH14.
3. Overdue & Late Payment Interest (Lãi suất chậm trả / Phạt vi phạm):
   Điều 357 & Điều 468 Bộ luật Dân sự 2015 (trần 20%/năm) và Điều 301 Luật Thương mại (trần 8%).
4. Land Transfer Taxes & Registration Fees (Thuế TNCN & Lệ phí trước bạ nhà đất):
   Luật Thuế TNCN & Nghị định 10/2022/NĐ-CP (Thuế TNCN 2% + Lệ phí trước bạ 0.5%).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CourtFeeResult(BaseModel):
    """Result of Court Legal Fee calculation under Resolution 326/2016/UBTVQH14."""

    dispute_type: str = Field(description="Loại tranh chấp (dân sự, hôn nhân, lao động, kinh doanh thương mại)")
    has_monetary_value: bool = Field(description="Có giá ngạch hay không có giá ngạch")
    claim_amount: float = Field(default=0.0, ge=0.0, description="Giá trị tranh chấp (VNĐ)")
    first_instance_fee: float = Field(description="Án phí dân sự sơ thẩm (VNĐ)")
    advance_fee: float = Field(description="Tạm ứng án phí sơ thẩm (50% án phí)")
    appellate_fee: float = Field(default=300000.0, description="Án phí phúc thẩm (VNĐ)")
    legal_basis: str = Field(default="Nghị quyết 326/2016/UBTVQH14", description="Căn cứ pháp lý")
    breakdown_formula: str = Field(description="Diễn giải chi tiết công thức tính")


class SeveranceCompensationResult(BaseModel):
    """Result of illegal termination compensation calculation under Labor Code 2019."""

    monthly_salary: float = Field(description="Mức tiền lương theo HĐLĐ (VNĐ)")
    months_worked: float = Field(description="Tổng thời gian làm việc thực tế (tháng)")
    days_without_notice: int = Field(default=0, description="Số ngày vi phạm thời hạn báo trước")
    
    salary_for_unnotified_days: float = Field(description="Tiền lương tương ứng ngày không báo trước (Điều 41.2)")
    minimum_compensation: float = Field(description="Ít nhất 02 tháng tiền lương theo HĐLĐ (Điều 41.1)")
    unemployed_days_salary: float = Field(description="Tiền lương trong những ngày không được làm việc (Điều 41.1)")
    severance_allowance: float = Field(default=0.0, description="Trợ cấp thôi việc nếu chưa đóng BHTN (Điều 46)")
    
    total_compensation: float = Field(description="Tổng số tiền người lao động được nhận (VNĐ)")
    legal_basis: str = Field(default="Điều 41, 46, 47 Bộ luật Lao động 2019", description="Căn cứ pháp lý")
    actionable_notes: list[str] = Field(default_factory=list, description="Lưu ý pháp lý quan trọng")


class InterestCalculationResult(BaseModel):
    """Result of overdue payment & statutory interest calculation."""

    principal_amount: float = Field(description="Số tiền gốc quá hạn (VNĐ)")
    days_overdue: int = Field(description="Số ngày chậm thanh toán")
    applied_annual_rate: float = Field(description="Lãi suất áp dụng (%/năm)")
    is_capped_by_law: bool = Field(default=False, description="Bị điều chỉnh do vượt trần luật định")
    total_interest: float = Field(description="Tổng số tiền lãi phát sinh (VNĐ)")
    total_payable: float = Field(description="Tổng số tiền gốc + lãi phải trả (VNĐ)")
    legal_basis: str = Field(description="Căn cứ pháp lý")
    warning_note: str | None = Field(default=None, description="Cảnh báo pháp lý nếu vượt trần")


class LandTransferTaxResult(BaseModel):
    """Result of Real Estate transfer taxes & registration fees calculation."""

    transfer_price: float = Field(description="Giá trị chuyển nhượng trên hợp đồng (VNĐ)")
    personal_income_tax: float = Field(description="Thuế TNCN (2% giá chuyển nhượng)")
    registration_fee: float = Field(description="Lệ phí trước bạ (0.5% giá trị)")
    notary_and_appraisal_est: float = Field(description="Ước tính phí công chứng & thẩm định hồ sơ (VNĐ)")
    total_taxes_and_fees: float = Field(description="Tổng thuế và lệ phí nhà nước (VNĐ)")
    legal_basis: str = Field(default="Luật Thuế TNCN & Nghị định 10/2022/NĐ-CP", description="Căn cứ pháp lý")
    exemptions_note: str = Field(description="Điều kiện miễn thuế (chuyển nhượng giữa cha mẹ, con cái, vợ chồng, nhà ở duy nhất)")


def calculate_court_fees(
    claim_amount: float,
    dispute_type: str = "dân sự",
    has_monetary_value: bool = True,
) -> CourtFeeResult:
    """Calculate Vietnam court legal fees based on Resolution 326/2016/UBTVQH14."""
    claim = max(0.0, float(claim_amount))
    dispute_type_lower = dispute_type.lower()

    # Trường hợp tranh chấp không có giá ngạch
    if not has_monetary_value or claim == 0:
        base_fee = 300000.0
        if "kinh doanh" in dispute_type_lower or "thương mại" in dispute_type_lower:
            base_fee = 3000000.0
        return CourtFeeResult(
            dispute_type=dispute_type,
            has_monetary_value=False,
            claim_amount=0.0,
            first_instance_fee=base_fee,
            advance_fee=base_fee * 0.5,
            appellate_fee=300000.0 if "kinh doanh" not in dispute_type_lower else 2000000.0,
            breakdown_formula=f"Tranh chấp không có giá ngạch theo Danh mục Nghị quyết 326/2016/UBTVQH14: Mức cố định {base_fee:,.0f} VNĐ.",
        )

    # Trường hợp tranh chấp Dân sự / Hôn nhân gia đình / Đất đai có giá ngạch
    fee = 0.0
    formula_text = ""

    if "kinh doanh" in dispute_type_lower or "thương mại" in dispute_type_lower:
        # Bảng án phí Kinh doanh thương mại sơ thẩm
        if claim <= 60000000:
            fee = 3000000.0
            formula_text = "Dưới 60 triệu VNĐ: Mức cố định 3.000.000 VNĐ."
        elif claim <= 400000000:
            fee = claim * 0.05
            formula_text = f"Từ 60 đến 400 triệu: 5% giá trị tranh chấp = 5% × {claim:,.0f} = {fee:,.0f} VNĐ."
        elif claim <= 2000000000:
            fee = 20000000.0 + (claim - 400000000.0) * 0.04
            formula_text = f"Từ 400 triệu đến 2 tỷ: 20.000.000 + 4% phần vượt 400 triệu = {fee:,.0f} VNĐ."
        elif claim <= 4000000000:
            fee = 84000000.0 + (claim - 2000000000.0) * 0.03
            formula_text = f"Từ 2 tỷ đến 4 tỷ: 84.000.000 + 3% phần vượt 2 tỷ = {fee:,.0f} VNĐ."
        else:
            fee = 144000000.0 + (claim - 4000000000.0) * 0.02
            formula_text = f"Trên 4 tỷ: 144.000.000 + 2% phần vượt 4 tỷ = {fee:,.0f} VNĐ."
    else:
        # Bảng án phí Dân sự có giá ngạch thông thường (Áp dụng cho Hợp đồng, Đất đai, Đòi nợ, Bồi thường thiệt hại)
        if claim <= 6000000:
            fee = 300000.0
            formula_text = "Từ 6 triệu VNĐ trở xuống: Mức tối thiểu 300.000 VNĐ."
        elif claim <= 400000000:
            fee = claim * 0.05
            formula_text = f"Từ trên 6 triệu đến 400 triệu VNĐ: 5% giá trị tranh chấp (5% × {claim:,.0f}) = {fee:,.0f} VNĐ."
        elif claim <= 800000000:
            fee = 20000000.0 + (claim - 400000000.0) * 0.04
            formula_text = f"Từ trên 400 triệu đến 800 triệu VNĐ: 20.000.000 + 4% của phần vượt 400 triệu = {fee:,.0f} VNĐ."
        elif claim <= 2000000000:
            fee = 36000000.0 + (claim - 800000000.0) * 0.03
            formula_text = f"Từ trên 800 triệu đến 2 tỷ VNĐ: 36.000.000 + 3% của phần vượt 800 triệu = {fee:,.0f} VNĐ."
        elif claim <= 4000000000:
            fee = 72000000.0 + (claim - 2000000000.0) * 0.02
            formula_text = f"Từ trên 2 tỷ đến 4 tỷ VNĐ: 72.000.000 + 2% của phần vượt 2 tỷ = {fee:,.0f} VNĐ."
        else:
            fee = 112000000.0 + (claim - 4000000000.0) * 0.001
            formula_text = f"Trên 4 tỷ VNĐ: 112.000.000 + 0.1% của phần vượt 4 tỷ = {fee:,.0f} VNĐ."

    advance = fee * 0.5
    return CourtFeeResult(
        dispute_type=dispute_type,
        has_monetary_value=True,
        claim_amount=claim,
        first_instance_fee=round(fee, 2),
        advance_fee=round(advance, 2),
        appellate_fee=300000.0,
        breakdown_formula=formula_text,
    )


def calculate_illegal_termination_compensation(
    monthly_salary: float,
    months_worked: float = 12.0,
    unemployed_months: float = 2.0,
    days_without_notice: int = 0,
    has_unemployment_insurance: bool = True,
) -> SeveranceCompensationResult:
    """Calculate illegal dismissal compensation under Article 41 of Vietnam Labor Code 2019."""
    salary = max(0.0, float(monthly_salary))
    worked_months = max(1.0, float(months_worked))
    daily_rate = salary / 26.0

    # 1. Tiền lương vi phạm thời hạn báo trước (Điều 41.2)
    unnotified_pay = round(days_without_notice * daily_rate, 2)

    # 2. Ít nhất 02 tháng tiền lương theo HĐLĐ (Điều 41.1)
    min_comp = round(2.0 * salary, 2)

    # 3. Tiền lương trong những ngày không được làm việc (Điều 41.1)
    unemployed_pay = round(max(0.0, float(unemployed_months)) * salary, 2)

    # 4. Trợ cấp thôi việc (nếu có thời gian không tham gia BHTN theo Điều 46)
    severance = 0.0
    if not has_unemployment_insurance:
        years_worked = worked_months / 12.0
        severance = round(years_worked * 0.5 * salary, 2)

    total = unnotified_pay + min_comp + unemployed_pay + severance

    notes = [
        "Người sử dụng lao động phải nhận người lao động trở lại làm việc theo HĐLĐ đã giao kết.",
        "Phải đóng bảo hiểm xã hội, bảo hiểm y tế, bảo hiểm thất nghiệp cho những ngày người lao động không được làm việc.",
        "Trường hợp người lao động không muốn tiếp tục làm việc thì ngoài các khoản trên, được nhận thêm Trợ cấp thôi việc theo Điều 46.",
        "Trường hợp NSDLĐ không muốn nhận lại và NLĐ đồng ý, hai bên thỏa thuận bồi thường thêm ít nhất 02 tháng tiền lương.",
    ]

    return SeveranceCompensationResult(
        monthly_salary=salary,
        months_worked=worked_months,
        days_without_notice=days_without_notice,
        salary_for_unnotified_days=unnotified_pay,
        minimum_compensation=min_comp,
        unemployed_days_salary=unemployed_pay,
        severance_allowance=severance,
        total_compensation=round(total, 2),
        actionable_notes=notes,
    )


def calculate_overdue_interest(
    principal_amount: float,
    days_overdue: int,
    agreed_annual_rate: float = 10.0,
    is_commercial_contract: bool = False,
) -> InterestCalculationResult:
    """Calculate overdue interest with statutory cap checks under Civil Code 2015 / Commercial Law."""
    principal = max(0.0, float(principal_amount))
    days = max(0, int(days_overdue))
    rate = float(agreed_annual_rate)

    capped = False
    warning = None
    applied_rate = rate

    # Trần lãi suất theo Điều 468 BLDS là 20%/năm
    if rate > 20.0:
        capped = True
        applied_rate = 20.0
        warning = f"Lãi suất thỏa thuận ({rate}%) vượt trần luật định 20%/năm theo Điều 468 Bộ luật Dân sự 2015. Phần vượt quá không có hiệu lực."

    # Tính lãi: Tiền gốc × Lãi suất năm / 365 × Số ngày
    interest = (principal * (applied_rate / 100.0) / 365.0) * days
    total = principal + interest

    legal_basis = "Điều 357 & Điều 468 Bộ luật Dân sự 2015"
    if is_commercial_contract:
        legal_basis = "Điều 306 Luật Thương mại 2005 & Điều 468 BLDS 2015"

    return InterestCalculationResult(
        principal_amount=principal,
        days_overdue=days,
        applied_annual_rate=applied_rate,
        is_capped_by_law=capped,
        total_interest=round(interest, 2),
        total_payable=round(total, 2),
        legal_basis=legal_basis,
        warning_note=warning,
    )


def calculate_land_transfer_taxes(
    property_value: float,
    is_first_and_only_home: bool = False,
    is_direct_family_transfer: bool = False,
) -> LandTransferTaxResult:
    """Calculate Personal Income Tax (2%) and Registration Fee (0.5%) for real estate transfer."""
    val = max(0.0, float(property_value))

    pit = 0.0
    reg_fee = 0.0
    exempt_notes = []

    if is_direct_family_transfer:
        exempt_notes.append("Chuyển nhượng giữa vợ với chồng; cha mẹ với con cái; ông bà với cháu; anh chị em ruột: Được MIỄN 100% Thuế TNCN và MIỄN Lệ phí trước bạ theo Điều 4 Luật Thuế TNCN.")
    elif is_first_and_only_home:
        exempt_notes.append("Chuyển nhượng bất động sản duy nhất của cá nhân: Được MIỄN Thuế TNCN 2% (vẫn nộp 0.5% Lệ phí trước bạ).")
        reg_fee = val * 0.005
    else:
        pit = val * 0.02
        reg_fee = val * 0.005
        exempt_notes.append("Chuyển nhượng thông thường: Người bán nộp 2% Thuế TNCN, Người mua nộp 0.5% Lệ phí trước bạ (trừ khi có thỏa thuận khác trong hợp đồng).")

    notary_est = 2000000.0 if val <= 1000000000.0 else 5000000.0
    total = pit + reg_fee + notary_est

    return LandTransferTaxResult(
        transfer_price=val,
        personal_income_tax=round(pit, 2),
        registration_fee=round(reg_fee, 2),
        notary_and_appraisal_est=notary_est,
        total_taxes_and_fees=round(total, 2),
        exemptions_note=" ".join(exempt_notes),
    )
