import type { CaseField } from '@/types';
import { fieldLabelForKey, fieldOptionsForKey } from '@/lib/userCopy';

export interface CaseFieldListProps {
  fields: CaseField[];
  values: Record<string, string>;
  validationErrors?: Record<string, string>;
  disabled?: boolean;
  onChange?: (key: string, value: string) => void;
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
                <input
                  aria-describedby={error ? `${field.key}-error` : undefined}
                  aria-label={label}
                  className={`mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-[#172033] outline-none transition placeholder:text-[#98a29f] focus:ring-2 focus:ring-[#0f766e]/15 disabled:bg-[#f1f4f3] ${error || field.missing ? 'border-[#d7a65a] focus:border-[#b7791f]' : 'border-[#bdc9c6] focus:border-[#0f766e]'}`}
                  disabled={disabled || !onChange}
                  max={field.key === 'annual_revenue_vnd' ? 1_000_000_000_000_000 : field.key === 'recovery_rate' ? 100 : undefined}
                  min={field.key === 'annual_revenue_vnd' || field.key === 'recovery_rate' ? 0 : undefined}
                  onChange={(event) => onChange?.(field.key, event.target.value)}
                  placeholder={field.kind === 'number' ? 'Nhập số tiền bằng VNĐ' : `Nhập ${label.toLowerCase()}`}
                  step={field.key === 'recovery_rate' ? '0.01' : field.kind === 'number' ? '1' : undefined}
                  type={field.kind === 'number' ? 'number' : 'text'}
                  value={value}
                />
              )}
              {error && <span className="mt-1 block text-xs font-normal text-[#ba1a1a]" id={`${field.key}-error`} role="alert">{error}</span>}
              {field.key === 'packaged_goods_category' && value === 'other' && <span className="mt-1 block text-xs font-normal text-[#9a5b18]">Nhóm “Khác” sẽ được giữ ở trạng thái chưa xác định nếu chưa có điều khoản đang áp dụng.</span>}
            </label>
          );
        })}
    </div>
  );
}
