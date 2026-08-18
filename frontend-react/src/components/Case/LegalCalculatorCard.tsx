import { Icon } from '@/components/UI/Icon';

export interface CourtFeeData {
  type: 'court_fee';
  claim_amount: number;
  first_instance_fee: number;
  advance_fee: number;
  appellate_fee: number;
  breakdown_formula: string;
  legal_basis: string;
}

export interface SeveranceData {
  type: 'severance';
  monthly_salary: number;
  salary_for_unnotified_days: number;
  minimum_compensation: number;
  unemployed_days_salary: number;
  severance_allowance: number;
  total_compensation: number;
  legal_basis: string;
  actionable_notes: string[];
}

export interface OverdueInterestData {
  type: 'interest';
  principal_amount: number;
  days_overdue: number;
  applied_annual_rate: number;
  is_capped_by_law: boolean;
  total_interest: number;
  total_payable: number;
  legal_basis: string;
  warning_note?: string | null;
}

export interface LandTaxData {
  type: 'land_tax';
  transfer_price: number;
  personal_income_tax: number;
  registration_fee: number;
  notary_and_appraisal_est: number;
  total_taxes_and_fees: number;
  legal_basis: string;
  exemptions_note: string;
}

export type CalculatorData = CourtFeeData | SeveranceData | OverdueInterestData | LandTaxData;

interface LegalCalculatorCardProps {
  data: CalculatorData;
}

function formatVND(amount: number): string {
  return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(amount);
}

export function LegalCalculatorCard({ data }: LegalCalculatorCardProps) {
  if (data.type === 'court_fee') {
    return (
      <div className="my-4 overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2.5 border-b border-slate-100 pb-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-teal-50 text-teal-800 ring-1 ring-teal-600/20">
            <Icon name="calculator" size={16} />
          </span>
          <div>
            <h4 className="text-sm font-bold text-slate-900">Bảng Tính Án phí Tòa án Nhân dân</h4>
            <p className="text-xs text-slate-500">{data.legal_basis}</p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
            <span className="text-[11px] font-semibold uppercase text-slate-500">Án phí Dân sự Sơ thẩm</span>
            <p className="mt-1 text-lg font-bold text-slate-900">{formatVND(data.first_instance_fee)}</p>
            <p className="mt-1 text-[11px] text-slate-600">{data.breakdown_formula}</p>
          </div>

          <div className="rounded-xl border border-teal-200 bg-teal-50/50 p-3">
            <span className="text-[11px] font-semibold uppercase text-teal-700">Tiền Tạm ứng Án phí (50%)</span>
            <p className="mt-1 text-lg font-bold text-teal-900">{formatVND(data.advance_fee)}</p>
            <p className="mt-1 text-[11px] text-slate-600">Số tiền người khởi kiện cần nộp trước tại Chi cục Thi hành án để Tòa án thụ lý vụ án.</p>
          </div>
        </div>
      </div>
    );
  }

  if (data.type === 'severance') {
    return (
      <div className="my-4 overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2.5 border-b border-slate-100 pb-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-teal-50 text-teal-800 ring-1 ring-teal-600/20">
            <Icon name="calculator" size={16} />
          </span>
          <div>
            <h4 className="text-sm font-bold text-slate-900">Bảng Tính Quyền lợi & Bồi thường khi bị Chấm dứt HĐLĐ</h4>
            <p className="text-xs text-slate-500">{data.legal_basis}</p>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 text-center">
          <span className="text-xs font-semibold text-emerald-800">TỔNG KHOẢN TIỀN NGƯỜI LAO ĐỘNG ĐƯỢC NHẬN</span>
          <p className="mt-1 text-2xl font-black text-emerald-900">{formatVND(data.total_compensation)}</p>
        </div>

        <div className="mt-3 grid gap-2 text-xs text-slate-700 sm:grid-cols-2">
          <div className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50/50 p-2.5">
            <span>Ít nhất 02 tháng lương bồi thường:</span>
            <span className="font-bold">{formatVND(data.minimum_compensation)}</span>
          </div>
          <div className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50/50 p-2.5">
            <span>Lương ngày không được làm việc:</span>
            <span className="font-bold">{formatVND(data.unemployed_days_salary)}</span>
          </div>
          {data.salary_for_unnotified_days > 0 && (
            <div className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50/50 p-2.5">
              <span>Lương vi phạm thời hạn báo trước:</span>
              <span className="font-bold">{formatVND(data.salary_for_unnotified_days)}</span>
            </div>
          )}
          {data.severance_allowance > 0 && (
            <div className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50/50 p-2.5">
              <span>Trợ cấp thôi việc (nếu có):</span>
              <span className="font-bold">{formatVND(data.severance_allowance)}</span>
            </div>
          )}
        </div>

        {data.actionable_notes.length > 0 && (
          <div className="mt-3 rounded-lg bg-slate-50 p-3 text-[11px] text-slate-600">
            <p className="font-semibold text-slate-800">Quy định luật định bắt buộc đối với NSDLĐ:</p>
            <ul className="mt-1 list-inside list-disc space-y-0.5">
              {data.actionable_notes.map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  }

  if (data.type === 'interest') {
    return (
      <div className="my-4 overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2.5 border-b border-slate-100 pb-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-teal-50 text-teal-800 ring-1 ring-teal-600/20">
            <Icon name="calculator" size={16} />
          </span>
          <div>
            <h4 className="text-sm font-bold text-slate-900">Bảng Tính Lãi Chậm trả & Tiền Quá hạn Hợp đồng</h4>
            <p className="text-xs text-slate-500">{data.legal_basis}</p>
          </div>
        </div>

        {data.warning_note && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50/80 p-3 text-xs text-rose-800">
            <p className="font-semibold">⚠️ Cảnh báo vượt trần lãi suất:</p>
            <p className="mt-0.5">{data.warning_note}</p>
          </div>
        )}

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
            <span className="text-[11px] font-semibold text-slate-500">Tiền Lãi Chậm trả ({data.applied_annual_rate}%/năm - {data.days_overdue} ngày)</span>
            <p className="mt-1 text-lg font-bold text-slate-900">{formatVND(data.total_interest)}</p>
          </div>
          <div className="rounded-xl border border-teal-200 bg-teal-50/50 p-3">
            <span className="text-[11px] font-semibold text-teal-700">Tổng Gốc + Lãi Phải Thanh toán</span>
            <p className="mt-1 text-lg font-bold text-teal-900">{formatVND(data.total_payable)}</p>
          </div>
        </div>
      </div>
    );
  }

  // Land tax
  return (
    <div className="my-4 overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2.5 border-b border-slate-100 pb-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-teal-50 text-teal-800 ring-1 ring-teal-600/20">
          <Icon name="calculator" size={16} />
        </span>
        <div>
          <h4 className="text-sm font-bold text-slate-900">Bảng Tính Thuế & Lệ phí Sang tên Nhà đất</h4>
          <p className="text-xs text-slate-500">{data.legal_basis}</p>
        </div>
      </div>

      <div className="mt-4 grid gap-2.5 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
          <span className="text-[11px] font-semibold text-slate-500">Thuế TNCN (2%)</span>
          <p className="mt-1 text-base font-bold text-slate-900">{formatVND(data.personal_income_tax)}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
          <span className="text-[11px] font-semibold text-slate-500">Lệ phí trước bạ (0.5%)</span>
          <p className="mt-1 text-base font-bold text-slate-900">{formatVND(data.registration_fee)}</p>
        </div>
        <div className="rounded-xl border border-teal-200 bg-teal-50/50 p-3">
          <span className="text-[11px] font-semibold text-teal-700">Tổng Thuế & Phí ước tính</span>
          <p className="mt-1 text-base font-bold text-teal-900">{formatVND(data.total_taxes_and_fees)}</p>
        </div>
      </div>

      <p className="mt-3 rounded-lg bg-slate-50 p-2.5 text-xs text-slate-600">
        <span className="font-semibold text-slate-800">Lưu ý miễn thuế:</span> {data.exemptions_note}
      </p>
    </div>
  );
}
