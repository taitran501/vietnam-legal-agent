import { useEffect, useMemo, useState } from 'react';
import { updateCaseState } from '@/api/sessions';
import { toast } from '@/components/UI/Toast';
import type { CaseFacts, CaseState } from '@/types';

const fields: Array<{ key: keyof CaseFacts; label: string; placeholder: string }> = [
  { key: 'business_role', label: 'Vai trò doanh nghiệp', placeholder: 'Ví dụ: Nhà sản xuất' },
  { key: 'product_or_packaging', label: 'Sản phẩm hoặc bao bì', placeholder: 'Ví dụ: Bao bì thực phẩm' },
  { key: 'material', label: 'Vật liệu chính', placeholder: 'Ví dụ: Nhựa PET' },
  { key: 'activity_scope', label: 'Phạm vi hoạt động', placeholder: 'Ví dụ: Thị trường Việt Nam' },
];

const taskLabel = {
  assess_epr_obligation: 'Đánh giá nghĩa vụ',
  build_compliance_checklist: 'Lập checklist',
};

interface CaseFactsPanelProps {
  conversationId: string | null;
  caseState: CaseState | null;
  onCaseChange: (caseState: CaseState) => void;
}

export function CaseFactsPanel({ conversationId, caseState, onCaseChange }: CaseFactsPanelProps) {
  const [facts, setFacts] = useState<CaseFacts>({});
  const [taskType, setTaskType] = useState<CaseState['task_type']>('assess_epr_obligation');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setFacts(caseState?.facts || {});
    setTaskType(caseState?.task_type || 'assess_epr_obligation');
  }, [caseState]);

  const missing = useMemo(() => new Set(caseState?.missing_facts || []), [caseState]);
  const isDisabled = !conversationId || saving;

  const save = async () => {
    if (!conversationId) {
      toast.info('Hãy gửi câu hỏi đầu tiên để tạo hồ sơ đánh giá.');
      return;
    }
    setSaving(true);
    try {
      const next = await updateCaseState(conversationId, facts, taskType);
      onCaseChange(next);
      toast.success('Đã cập nhật thông tin trường hợp');
    } catch {
      toast.error('Không thể lưu thông tin trường hợp');
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside className="flex h-full flex-col border-l border-slate-200 bg-slate-50/70 p-4" aria-label="Thông tin trường hợp">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-teal-800">Hồ sơ trường hợp</p>
          <h2 className="mt-1 text-base font-semibold text-slate-900">Facts doanh nghiệp</h2>
        </div>
        {caseState && (
          <span className="rounded-full bg-teal-50 px-2 py-1 text-xs font-medium text-teal-800">
            {caseState.status === 'collecting' ? 'Cần bổ sung' : caseState.status === 'ready' ? 'Sẵn sàng' : 'Đã hoàn tất'}
          </span>
        )}
      </div>

      <label className="mb-4 block text-sm font-medium text-slate-700">
        Mục tiêu
        <select
          value={taskType}
          disabled={isDisabled}
          onChange={(event) => setTaskType(event.target.value as CaseState['task_type'])}
          className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/15 disabled:bg-slate-100"
        >
          <option value="assess_epr_obligation">{taskLabel.assess_epr_obligation}</option>
          <option value="build_compliance_checklist">{taskLabel.build_compliance_checklist}</option>
        </select>
      </label>

      <div className="space-y-3">
        {fields.map((field) => (
          <label key={field.key} className="block text-sm font-medium text-slate-700">
            <span className="flex items-center gap-1.5">
              {field.label}
              {missing.has(field.key) && <span className="text-xs font-normal text-amber-700">cần bổ sung</span>}
            </span>
            <input
              value={facts[field.key] || ''}
              disabled={isDisabled}
              onChange={(event) => setFacts((current) => ({ ...current, [field.key]: event.target.value }))}
              placeholder={field.placeholder}
              className={`mt-1.5 w-full rounded-lg border bg-white px-3 py-2 text-sm outline-none transition focus:ring-2 focus:ring-teal-700/15 disabled:bg-slate-100 ${
                missing.has(field.key) ? 'border-amber-300 focus:border-amber-500' : 'border-slate-300 focus:border-teal-700'
              }`}
            />
          </label>
        ))}
      </div>

      <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
        Chỉ nhập thông tin bạn đã xác nhận. Hệ thống không suy đoán facts còn thiếu và kết quả chỉ là đánh giá sơ bộ.
      </div>
      <button
        type="button"
        onClick={save}
        disabled={isDisabled}
        className="mt-4 rounded-lg bg-teal-800 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-teal-900 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {saving ? 'Đang lưu…' : 'Lưu thông tin trường hợp'}
      </button>
    </aside>
  );
}
