import type { CaseField } from '@/types';
import { fieldLabelForKey, fieldOptionsForKey } from '@/lib/userCopy';

export interface CaseFieldListProps {
  fields: CaseField[];
  values: Record<string, string>;
  validationErrors?: Record<string, string>;
  disabled?: boolean;
  onChange?: (key: string, value: string) => void;
}

const revenuePresets = [
  { label: '< 30 tỷ (20 tỷ)', value: '20000000000' },
  { label: '30 tỷ (Mốc chuẩn)', value: '30000000000' },
  { label: '50 tỷ', value: '50000000000' },
  { label: '100 tỷ', value: '100000000000' },
];

const fieldExamples: Record<string, string> = {
  object_kind: '💡 Ví dụ: Chai lọ, hộp, túi nilon, màng bọc (Bao bì thương phẩm) hoặc thiết bị, phụ tùng (Sản phẩm).',
  packaged_goods_category: '💡 Ví dụ: Đóng gói thực phẩm, mỹ phẩm, dược phẩm, hóa chất tẩy rửa, xi măng...',
  material: '💡 Ví dụ: Nhựa PET, màng PE/PP, Giấy/Carton, Kim loại, Thủy tinh...',
};

function formatVndPreview(value: string): string | null {
  const digits = value.replace(/\D/g, '');
  if (!digits) return null;
  const num = Number(digits);
  if (isNaN(num) || num <= 0) return null;
  const formatted = num.toLocaleString('vi-VN');
  let words = '';
  if (num >= 1_000_000_000) {
    const ty = num / 1_000_000_000;
    words = `${ty.toLocaleString('vi-VN', { maximumFractionDigits: 2 })} tỷ đồng`;
  } else if (num >= 1_000_000) {
    const tr = num / 1_000_000;
    words = `${tr.toLocaleString('vi-VN', { maximumFractionDigits: 2 })} triệu đồng`;
  }
  return words ? `${formatted} VNĐ (~${words})` : `${formatted} VNĐ`;
}

export function CaseFieldList({ fields, values, validationErrors = {}, disabled = false, onChange }: CaseFieldListProps) {
  return (
    <div className="space-y-4">
      {fields
        .slice()
        .sort((left, right) => (left.display_order ?? 0) - (right.display_order ?? 0))
        .map((field) => {
          const label = fieldLabelForKey(field.key, field.label);
          const value = values[field.key] ?? field.value ?? '';
          const error = validationErrors[field.key];
          const requiredText = field.importance === 'required' ? 'bắt buộc' : field.importance === 'conditional' ? 'tùy trường hợp' : 'tham khảo';
          const example = fieldExamples[field.key];
          const vndPreview = field.key === 'annual_revenue_vnd' ? formatVndPreview(value) : null;

          return (
            <label className="block text-sm font-medium text-[#3e4947]" key={field.key}>
              <span className="flex flex-wrap items-center gap-1.5">
                {label}
                {field.importance && <span className="text-[10px] font-normal uppercase tracking-wide text-[#667085]">{requiredText}</span>}
                {field.missing && <span className="text-xs font-normal text-[#9a5b18]">cần bổ sung</span>}
              </span>
              <span className="mt-1 block text-xs font-normal leading-5 text-[#7a8582]">
                {field.help_text || 'Thông tin này giúp chọn đúng quy định cần đối chiếu.'}
              </span>
              {example && (
                <span className="mt-0.5 block text-[11px] font-normal text-[#006a63]">
                  {example}
                </span>
              )}
              {field.kind === 'select' ? (
                <select
                  aria-describedby={error ? `${field.key}-error` : undefined}
                  aria-label={label}
                  className={`mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-[#172033] outline-none transition focus:ring-2 focus:ring-[#0f766e]/15 disabled:bg-[#f1f4f3] ${error || field.missing ? 'border-[#d7a65a] focus:border-[#b7791f]' : 'border-[#bdc9c6] focus:border-[#0f766e]'}`}
                  disabled={disabled || !onChange}
                  onChange={(event) => onChange?.(field.key, event.target.value)}
                  value={value}
                >
                  <option value="">Chọn thông tin</option>
                  {fieldOptionsForKey(field.key, field.options).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              ) : (
                <div className="space-y-1.5">
                  <input
                    aria-describedby={error ? `${field.key}-error` : undefined}
                    aria-label={label}
                    className={`mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-[#172033] outline-none transition placeholder:text-[#98a29f] focus:ring-2 focus:ring-[#0f766e]/15 disabled:bg-[#f1f4f3] ${error || field.missing ? 'border-[#d7a65a] focus:border-[#b7791f]' : 'border-[#bdc9c6] focus:border-[#0f766e]'}`}
                    disabled={disabled || !onChange}
                    max={field.key === 'annual_revenue_vnd' ? 1_000_000_000_000_000 : field.key === 'recovery_rate' ? 100 : undefined}
                    min={field.key === 'annual_revenue_vnd' || field.key === 'recovery_rate' ? 0 : undefined}
                    onChange={(event) => onChange?.(field.key, event.target.value)}
                    placeholder={field.kind === 'number' ? 'Nhập số tiền bằng VNĐ (vd: 30000000000)' : `Nhập ${label.toLowerCase()}`}
                    step={field.key === 'recovery_rate' ? '0.01' : field.kind === 'number' ? '1' : undefined}
                    type={field.kind === 'number' ? 'number' : 'text'}
                    value={value}
                  />
                  {field.key === 'annual_revenue_vnd' && (
                    <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                      <span className="text-[11px] text-[#667085]">Chọn nhanh:</span>
                      {revenuePresets.map((preset) => (
                        <button
                          className={`rounded border px-2 py-0.5 text-[11px] font-medium transition ${value === preset.value ? 'border-[#0f766e] bg-[#e0f2fe] text-[#005c55]' : 'border-[#d9e1df] bg-[#f8faf9] text-[#53615e] hover:border-[#0f766e] hover:text-[#006a63]'}`}
                          disabled={disabled || !onChange}
                          key={preset.value}
                          onClick={(e) => {
                            e.preventDefault();
                            onChange?.('annual_revenue_vnd', preset.value);
                          }}
                          type="button"
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  )}
                  {vndPreview && (
                    <div className="inline-flex items-center gap-1.5 rounded-md bg-[#e6f4f2] px-2.5 py-1 text-xs font-medium text-[#006a63]">
                      <span>👉</span>
                      <span>{vndPreview}</span>
                    </div>
                  )}
                </div>
              )}
              {error && <span className="mt-1 block text-xs font-normal text-[#ba1a1a]" id={`${field.key}-error`} role="alert">{error}</span>}
              {field.key === 'packaged_goods_category' && value === 'other' && <span className="mt-1 block text-xs font-normal text-[#9a5b18]">Nhóm “Khác” sẽ được giữ ở trạng thái chưa xác định nếu chưa có điều khoản đang áp dụng.</span>}
            </label>
          );
        })}
    </div>
  );
}
