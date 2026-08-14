import { useEffect, useMemo, useState } from 'react';
import { updateCaseState } from '@/api/sessions';
import { toast } from '@/state/toastStore';
import type { CaseField, CaseState, FactValue } from '@/types';
import { CaseFieldList } from './CaseFieldList';
import { fieldLabelForKey, fieldOptionsForKey, taskCopy } from '@/lib/userCopy';

function fallbackFieldLabel(key: string): string {
  return fieldLabelForKey(key);
}

interface CaseFactsPanelProps {
  conversationId: string | null;
  caseState: CaseState | null;
  onCaseChange: (caseState: CaseState) => void;
  onContinue: (
    facts: Record<string, string>,
    confirmationStatuses?: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>,
    taskType?: CaseState['task_type'],
  ) => void;
  onDirtyChange?: (dirty: boolean) => void;
}

function plainFactValue(value: string | FactValue | undefined): string {
  return typeof value === 'string' ? value : value?.value || '';
}

export function CaseFactsPanel({ conversationId, caseState, onCaseChange, onContinue, onDirtyChange }: CaseFactsPanelProps) {
  const [facts, setFacts] = useState<Record<string, string>>({});
  const [taskType, setTaskType] = useState<CaseState['task_type']>('assess_epr_obligation');
  const [saving, setSaving] = useState(false);
  const [baseline, setBaseline] = useState<Record<string, string>>({});
  const [baselineTaskType, setBaselineTaskType] = useState<CaseState['task_type']>('assess_epr_obligation');
  const [confirmationStatuses, setConfirmationStatuses] = useState<Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>>({});
  const [baselineConfirmationStatuses, setBaselineConfirmationStatuses] = useState<Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>>({});
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const nextFacts = Object.fromEntries(Object.entries(caseState?.facts || {}).map(([key, value]) => [key, plainFactValue(value)]));
    for (const field of caseState?.fields || []) {
      if (!nextFacts[field.key] && field.value) nextFacts[field.key] = field.value;
    }
    setFacts(nextFacts);
    setBaseline(nextFacts);
    const nextStatuses = Object.fromEntries(Object.entries(caseState?.facts || {}).map(([key, value]) => [
      key,
      typeof value === 'string' ? 'unknown' : value.confirmation_status || 'unknown',
    ])) as Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>;
    setConfirmationStatuses(nextStatuses);
    setBaselineConfirmationStatuses(nextStatuses);
    setValidationErrors({});
    const nextTaskType = caseState?.task_type || 'assess_epr_obligation';
    setTaskType(nextTaskType);
    setBaselineTaskType(nextTaskType);
  }, [caseState]);

  const missing = useMemo(() => new Set(caseState?.missing_facts || []), [caseState]);
  const isDisabled = !conversationId || saving;
  const dynamicFields: CaseField[] = caseState?.fields || Object.keys(facts).map((key) => ({
    key,
    label: fallbackFieldLabel(key),
    kind: fieldOptionsForKey(key).length ? 'select' : 'text',
    options: fieldOptionsForKey(key),
    required: true,
    importance: 'required',
    missing: missing.has(key),
    value: facts[key] || '',
  }));
  const requiredFields = dynamicFields.filter((field) => field.required);
  const filledRequired = requiredFields.filter((field) => Boolean(facts[field.key])).length;
  const submissionBlockedReason = caseState?.submission_blocked_reason || '';
  const isDirty = JSON.stringify(facts) !== JSON.stringify(baseline)
    || JSON.stringify(confirmationStatuses) !== JSON.stringify(baselineConfirmationStatuses)
    || taskType !== baselineTaskType;
  const hasRequiredFacts = filledRequired === requiredFields.length
    && Object.keys(validationErrors).length === 0
    && (!submissionBlockedReason || isDirty);

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  const validateField = (key: string, value: string): string | undefined => {
    if (!value.trim()) return undefined;
    if (key === 'annual_revenue_vnd' && (!/^\d+$/.test(value) || Number(value) > 1_000_000_000_000_000)) {
      return 'Doanh thu phải là số nguyên không âm và không vượt quá 1.000.000.000.000.000 VNĐ.';
    }
    if (key === 'recovery_rate' && (!/^\d+(\.\d+)?$/.test(value) || Number(value) < 0 || Number(value) > 100)) {
      return 'Tỷ lệ phải nằm trong khoảng 0–100.';
    }
    return undefined;
  };

  const changeFact = (key: string, value: string) => {
    setFacts((current) => ({ ...current, [key]: value }));
    setConfirmationStatuses((current) => ({ ...current, [key]: 'user_confirmed' }));
    const error = validateField(key, value);
    setValidationErrors((current) => {
      const next = { ...current };
      if (error) next[key] = error;
      else delete next[key];
      return next;
    });
  };

  const save = async (): Promise<boolean> => {
    if (!conversationId) {
      toast.info('Hãy gửi câu hỏi đầu tiên để tạo hồ sơ đánh giá.');
      return false;
    }
    if (Object.keys(validationErrors).length > 0) return false;
    setSaving(true);
    try {
      const next = await updateCaseState(conversationId, facts, taskType, confirmationStatuses);
      onCaseChange(next);
      setBaseline(facts);
      setBaselineConfirmationStatuses(confirmationStatuses);
      setBaselineTaskType(taskType);
      if (next.submission_blocked_reason) {
        toast.info(next.submission_blocked_reason);
        return false;
      }
      toast.success('Đã cập nhật thông tin trường hợp');
      return true;
    } catch {
      toast.error('Không thể lưu thông tin trường hợp');
      return false;
    } finally {
      setSaving(false);
    }
  };

  const continueCase = async () => {
    if (!hasRequiredFacts) {
      toast.info('Hãy bổ sung và kiểm tra các thông tin bắt buộc trước khi tiếp tục.');
      return;
    }
    const saved = isDirty ? await save() : true;
    if (saved) onContinue(facts, confirmationStatuses, taskType);
  };

  const discard = () => {
    if (isDirty && !window.confirm('Bỏ các thay đổi chưa lưu?')) return;
    setFacts(baseline);
    setConfirmationStatuses(baselineConfirmationStatuses);
    setTaskType(baselineTaskType);
    setValidationErrors({});
  };

  return (
    <section className="flex min-h-full flex-col p-5" aria-label="Thông tin trường hợp">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#006a63]">Phạm vi EPR hiện tại</p>
          <h3 className="mt-1 text-base font-semibold text-[#172033]">Thông tin đã xác nhận</h3>
          {requiredFields.length > 0 && (
            <p className="mt-1 text-xs text-[#66736f]">
              Đã có {filledRequired}/{requiredFields.length} thông tin cần thiết
            </p>
          )}
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
          <option value="assess_epr_obligation">{taskCopy.assess_epr_obligation.action}</option>
          <option value="build_compliance_checklist">{taskCopy.build_compliance_checklist.action}</option>
        </select>
      </label>

      <CaseFieldList
        disabled={isDisabled}
        fields={dynamicFields}
        onChange={changeFact}
        validationErrors={validationErrors}
        values={facts}
      />
      {submissionBlockedReason && (
        <p className="mt-3 rounded-lg border border-[#ead6b8] bg-[#fff8ea] p-3 text-xs leading-5 text-[#714b18]" role="status">
          {submissionBlockedReason}
        </p>
      )}

      <div className="mt-5 rounded-lg border border-[#ead6b8] bg-[#fff8ea] p-3 text-xs leading-5 text-[#714b18]">
        Bạn đang xác nhận thông tin do mình nhập; điều này không có nghĩa là tài liệu hoặc cơ quan độc lập đã xác minh. Trợ lý không tự suy đoán dữ liệu doanh nghiệp còn thiếu.
      </div>
      {isDirty && <button type="button" onClick={discard} disabled={isDisabled} className="mt-3 rounded-lg border border-[#bdc9c6] bg-white px-3 py-2 text-sm font-semibold text-[#3e4947] disabled:cursor-not-allowed">Bỏ thay đổi</button>}
      <button
        type="button"
        onClick={save}
        disabled={isDisabled}
        className="mt-4 rounded-lg border border-[#bdc9c6] bg-white px-3 py-2.5 text-sm font-semibold text-[#3e4947] transition hover:bg-[#f1f4f3] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:text-[#7a8582]"
      >
        {saving ? 'Đang lưu…' : 'Lưu để hoàn thiện sau'}
      </button>
      <button type="button" onClick={() => void continueCase()} disabled={isDisabled || !hasRequiredFacts} className="mt-2 rounded-lg bg-[#0f766e] px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-[#005c55] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-[#bdc9c6]">
        {taskType === 'build_compliance_checklist' ? 'Lưu và tiếp tục tạo danh sách việc cần làm' : 'Lưu và tiếp tục đánh giá'}
      </button>
    </section>
  );
}
