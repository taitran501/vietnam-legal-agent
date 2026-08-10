import { useEffect, useMemo, useState } from 'react';
import { updateCaseState } from '@/api/sessions';
import { toast } from '@/state/toastStore';
import type { CaseField, CaseState, FactValue } from '@/types';

const taskLabel = {
  assess_epr_obligation: 'Đánh giá nghĩa vụ',
  build_compliance_checklist: 'Lập checklist',
};

interface CaseFactsPanelProps {
  conversationId: string | null;
  caseState: CaseState | null;
  onCaseChange: (caseState: CaseState) => void;
  onContinue: (facts: Record<string, string>) => void;
}

function plainFactValue(value: string | FactValue | undefined): string {
  return typeof value === 'string' ? value : value?.value || '';
}

export function CaseFactsPanel({ conversationId, caseState, onCaseChange, onContinue }: CaseFactsPanelProps) {
  const [facts, setFacts] = useState<Record<string, string>>({});
  const [taskType, setTaskType] = useState<CaseState['task_type']>('assess_epr_obligation');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setFacts(Object.fromEntries(Object.entries(caseState?.facts || {}).map(([key, value]) => [key, plainFactValue(value)])));
    setTaskType(caseState?.task_type || 'assess_epr_obligation');
  }, [caseState]);

  const missing = useMemo(() => new Set(caseState?.missing_facts || []), [caseState]);
  const isDisabled = !conversationId || saving;
  const dynamicFields: CaseField[] = caseState?.fields || Object.keys(facts).map((key) => ({
    key,
    label: key,
    kind: 'text',
    options: [],
    required: false,
    missing: missing.has(key),
    value: facts[key] || '',
  }));

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
    <section className="flex min-h-full flex-col p-5" aria-label="Thông tin trường hợp">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#006a63]">Phạm vi EPR hiện tại</p>
          <h3 className="mt-1 text-base font-semibold text-[#172033]">Dữ liệu đánh giá</h3>
        </div>
        {caseState && (
          <span className="rounded-full bg-[#e7eceb] px-2.5 py-1 text-xs font-medium text-[#006a63]">
            {caseState.status === 'collecting' ? 'Cần bổ sung' : caseState.status === 'ready' ? 'Sẵn sàng' : 'Đã hoàn tất'}
          </span>
        )}
      </div>

      <label className="mb-4 block text-sm font-medium text-[#3e4947]">
        Mục tiêu
        <select
          value={taskType}
          disabled={isDisabled}
          onChange={(event) => setTaskType(event.target.value as CaseState['task_type'])}
          className="mt-1.5 w-full rounded-lg border border-[#bdc9c6] bg-white px-3 py-2.5 text-sm text-[#172033] outline-none transition focus:border-[#0f766e] focus:ring-2 focus:ring-[#0f766e]/15 disabled:bg-[#f1f4f3]"
        >
          <option value="assess_epr_obligation">{taskLabel.assess_epr_obligation}</option>
          <option value="build_compliance_checklist">{taskLabel.build_compliance_checklist}</option>
        </select>
      </label>

      <div className="space-y-3">
        {dynamicFields.map((field) => (
          <label key={field.key} className="block text-sm font-medium text-[#3e4947]">
            <span className="flex items-center gap-1.5">
              {field.label}
              {missing.has(field.key) && <span className="text-xs font-normal text-[#9a5b18]">cần bổ sung</span>}
            </span>
            {field.kind === 'select' ? (
              <select value={facts[field.key] || ''} disabled={isDisabled} onChange={(event) => setFacts((current) => ({ ...current, [field.key]: event.target.value }))} className={`mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-[#172033] outline-none transition focus:ring-2 focus:ring-[#0f766e]/15 disabled:bg-[#f1f4f3] ${missing.has(field.key) ? 'border-[#d7a65a] focus:border-[#b7791f]' : 'border-[#bdc9c6] focus:border-[#0f766e]'}`}>
                <option value="">Chọn thông tin</option>
                {field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            ) : (
              <input value={facts[field.key] || ''} disabled={isDisabled} onChange={(event) => setFacts((current) => ({ ...current, [field.key]: event.target.value }))} placeholder={field.help_text || `Nhập ${field.label.toLowerCase()}`} type={field.kind === 'number' ? 'number' : 'text'} className={`mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-[#172033] outline-none transition placeholder:text-[#98a29f] focus:ring-2 focus:ring-[#0f766e]/15 disabled:bg-[#f1f4f3] ${missing.has(field.key) ? 'border-[#d7a65a] focus:border-[#b7791f]' : 'border-[#bdc9c6] focus:border-[#0f766e]'}`} />
            )}
          </label>
        ))}
      </div>

      <div className="mt-5 rounded-lg border border-[#ead6b8] bg-[#fff8ea] p-3 text-xs leading-5 text-[#714b18]">
        Chỉ nhập thông tin đã được xác nhận. Trợ lý không tự suy đoán dữ liệu doanh nghiệp còn thiếu.
      </div>
      <button
        type="button"
        onClick={save}
        disabled={isDisabled}
        className="mt-4 rounded-lg bg-[#0f766e] px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-[#005c55] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-[#bdc9c6]"
      >
        {saving ? 'Đang lưu…' : 'Lưu thông tin trường hợp'}
      </button>
      <button type="button" onClick={() => onContinue(facts)} disabled={isDisabled || Boolean(caseState?.missing_facts.length)} className="mt-2 rounded-lg border border-[#0f766e] bg-white px-3 py-2.5 text-sm font-semibold text-[#006a63] transition hover:bg-[#f0faf8] disabled:cursor-not-allowed disabled:border-[#bdc9c6] disabled:text-[#7a8582]">
        Tiếp tục đánh giá
      </button>
    </section>
  );
}
