import { useEffect, useMemo, useState } from 'react';
import { updateCaseState } from '@/api/sessions';
import { toast } from '@/state/toastStore';
import type { CaseField, CaseState, FactValue } from '@/types';

const taskLabel = {
  assess_epr_obligation: 'Đánh giá nghĩa vụ',
  build_compliance_checklist: 'Lập checklist',
};

const fieldLabels: Record<string, string> = {
  business_role: 'Vai trò doanh nghiệp',
  object_kind: 'Loại đối tượng',
  product_group: 'Nhóm sản phẩm EPR',
  packaged_goods_category: 'Nhóm hàng hóa được đóng gói',
  material: 'Vật liệu hoặc quy cách',
  market_placement: 'Phạm vi đưa ra thị trường',
  activity_purpose: 'Mục đích sản xuất hoặc nhập khẩu',
  annual_revenue_vnd: 'Doanh thu bán sản phẩm liên quan mỗi năm',
  reused_by_producer: 'Bao bì có được chính doanh nghiệp thu hồi để tái sử dụng không',
  recovery_rate: 'Tỷ lệ thu hồi và tái sử dụng',
};

const fallbackOptions: Record<string, Array<{ value: string; label: string }>> = {
  business_role: [
    { value: 'manufacturer', label: 'Nhà sản xuất' },
    { value: 'importer', label: 'Nhà nhập khẩu' },
  ],
  object_kind: [
    { value: 'product', label: 'Sản phẩm' },
    { value: 'commercial_packaging', label: 'Bao bì thương phẩm' },
    { value: 'raw_material', label: 'Nguyên liệu' },
    { value: 'production_waste', label: 'Chất thải sản xuất' },
  ],
  product_group: [
    { value: 'bao_bi', label: 'Bao bì' },
    { value: 'ac_quy', label: 'Ắc quy' },
    { value: 'pin', label: 'Pin' },
    { value: 'dau_nhot', label: 'Dầu nhớt' },
    { value: 'sam_lop', label: 'Săm lốp' },
    { value: 'dien_tu', label: 'Điện - điện tử' },
    { value: 'phuong_tien', label: 'Phương tiện' },
  ],
  packaged_goods_category: [
    { value: 'thuc_pham', label: 'Thực phẩm' },
    { value: 'my_pham', label: 'Mỹ phẩm' },
    { value: 'thuoc', label: 'Thuốc' },
    { value: 'phan_bon_thuc_an_thu_y', label: 'Phân bón/thức ăn chăn nuôi/thuốc thú y' },
    { value: 'che_pham_tay_rua', label: 'Chế phẩm tẩy rửa' },
    { value: 'xi_mang', label: 'Xi măng' },
    { value: 'other', label: 'Khác' },
  ],
  material: [
    { value: 'plastic', label: 'Nhựa' },
    { value: 'pet', label: 'Nhựa PET' },
    { value: 'pe_pp', label: 'Nhựa PE/PP' },
    { value: 'paper', label: 'Giấy' },
    { value: 'glass', label: 'Thủy tinh' },
    { value: 'metal', label: 'Kim loại' },
    { value: 'rubber', label: 'Cao su' },
  ],
  market_placement: [
    { value: 'vietnam_market', label: 'Đưa ra thị trường Việt Nam' },
    { value: 'export_only', label: 'Chỉ xuất khẩu' },
    { value: 'temporary_import_reexport', label: 'Tạm nhập - tái xuất' },
  ],
  activity_purpose: [
    { value: 'commercial', label: 'Kinh doanh thương mại' },
    { value: 'research_study_test', label: 'Nghiên cứu/học tập/thử nghiệm' },
  ],
  reused_by_producer: [
    { value: 'yes', label: 'Có' },
    { value: 'no', label: 'Không' },
  ],
};

function fallbackFieldLabel(key: string): string {
  return fieldLabels[key] || 'Thông tin bổ sung';
}

function displayFieldLabel(field: Pick<CaseField, 'key' | 'label'>): string {
  if (fieldLabels[field.key]) return fieldLabels[field.key];
  if (field.label && field.label !== field.key && !field.label.includes('_')) return field.label;
  return fallbackFieldLabel(field.key);
}

function displayOptions(field: CaseField): Array<{ value: string; label: string }> {
  const defaults = fallbackOptions[field.key] || [];
  const defaultLabels = new Map(defaults.map((option) => [option.value, option.label]));
  return (field.options.length ? field.options : defaults).map((option) => ({
    ...option,
    label: defaultLabels.get(option.value) || (option.label.includes('_') ? option.value : option.label),
  }));
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
    kind: fallbackOptions[key] ? 'select' : 'text',
    options: fallbackOptions[key] || [],
    required: true,
    importance: 'required',
    missing: missing.has(key),
    value: facts[key] || '',
  }));
  const requiredFields = dynamicFields.filter((field) => field.required);
  const filledRequired = requiredFields.filter((field) => Boolean(facts[field.key])).length;
  const isDirty = JSON.stringify(facts) !== JSON.stringify(baseline)
    || JSON.stringify(confirmationStatuses) !== JSON.stringify(baselineConfirmationStatuses)
    || taskType !== baselineTaskType;
  const hasRequiredFacts = filledRequired === requiredFields.length && Object.keys(validationErrors).length === 0;

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
          <option value="assess_epr_obligation">{taskLabel.assess_epr_obligation}</option>
          <option value="build_compliance_checklist">{taskLabel.build_compliance_checklist}</option>
        </select>
      </label>

      <div className="space-y-3">
        {dynamicFields.map((field) => {
          const label = displayFieldLabel(field);
          const options = displayOptions(field);
          return (
          <label key={field.key} className="block text-sm font-medium text-[#3e4947]">
            <span className="flex items-center gap-1.5">
              {label}
              {field.importance && <span className="text-[10px] font-normal uppercase tracking-wide text-[#667085]">{field.importance === 'required' ? 'bắt buộc' : field.importance === 'conditional' ? 'tùy trường hợp' : 'tham khảo'}</span>}
              {(missing.has(field.key) || field.missing) && <span className="text-xs font-normal text-[#9a5b18]">cần bổ sung</span>}
            </span>
            <span className="mt-1 block text-xs font-normal leading-5 text-[#7a8582]">{field.help_text || 'Thông tin này có thể thay đổi kết luận hoặc căn cứ cần đối chiếu.'}</span>
            {field.kind === 'select' ? (
              <select aria-label={label} value={facts[field.key] || field.value || ''} disabled={isDisabled} onChange={(event) => changeFact(field.key, event.target.value)} className={`mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-[#172033] outline-none transition focus:ring-2 focus:ring-[#0f766e]/15 disabled:bg-[#f1f4f3] ${(missing.has(field.key) || field.missing) ? 'border-[#d7a65a] focus:border-[#b7791f]' : 'border-[#bdc9c6] focus:border-[#0f766e]'}`}>
                <option value="">Chọn thông tin</option>
                {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            ) : (
              <input aria-label={label} value={facts[field.key] || field.value || ''} disabled={isDisabled} onChange={(event) => changeFact(field.key, event.target.value)} min={field.key === 'annual_revenue_vnd' || field.key === 'recovery_rate' ? 0 : undefined} max={field.key === 'annual_revenue_vnd' ? 1_000_000_000_000_000 : field.key === 'recovery_rate' ? 100 : undefined} step={field.key === 'recovery_rate' ? '0.01' : field.kind === 'number' ? '1' : undefined} placeholder={field.kind === 'number' ? 'Nhập số tiền bằng VNĐ' : `Nhập ${label.toLowerCase()}`} type={field.kind === 'number' ? 'number' : 'text'} className={`mt-1.5 w-full rounded-lg border bg-white px-3 py-2.5 text-sm text-[#172033] outline-none transition placeholder:text-[#98a29f] focus:ring-2 focus:ring-[#0f766e]/15 disabled:bg-[#f1f4f3] ${(missing.has(field.key) || field.missing) ? 'border-[#d7a65a] focus:border-[#b7791f]' : 'border-[#bdc9c6] focus:border-[#0f766e]'}`} />
            )}
            {validationErrors[field.key] && <span className="mt-1 block text-xs font-normal text-[#ba1a1a]" role="alert">{validationErrors[field.key]}</span>}
            {field.key === 'packaged_goods_category' && facts[field.key] === 'other' && <span className="mt-1 block text-xs font-normal text-[#9a5b18]">Nhóm “Khác” sẽ được giữ ở trạng thái chưa xác định nếu chưa có điều khoản đang áp dụng.</span>}
          </label>
          );
        })}
      </div>

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
        {taskType === 'build_compliance_checklist' ? 'Lưu và tiếp tục lập checklist' : 'Lưu và tiếp tục đánh giá'}
      </button>
    </section>
  );
}
