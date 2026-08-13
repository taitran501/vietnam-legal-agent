import { useEffect } from 'react';
import type { CaseFormState, CaseState } from '@/types';
import { useCaseDraft } from '@/hooks/useCaseDraft';
import { CaseFieldList } from './CaseFieldList';
import { Icon } from '@/components/UI/Icon';
import { factLabels, taskCopy } from '@/lib/userCopy';

type ConfirmationStatus = 'user_confirmed' | 'document_verified' | 'unknown';

interface GuidedCaseCardProps {
  taskType: CaseState['task_type'];
  initialCaseState?: CaseState | CaseFormState | null;
  active?: boolean;
  onSubmit: (facts: Record<string, string>, statuses: Record<string, ConfirmationStatus>, taskType: CaseState['task_type']) => Promise<void>;
  onOpenFullEditor?: () => void;
  onDraftChange?: (facts: Record<string, string>, statuses: Record<string, ConfirmationStatus>, formState: CaseFormState | null) => void;
}

export function GuidedCaseCard({ taskType, initialCaseState, active = true, onSubmit, onOpenFullEditor, onDraftChange }: GuidedCaseCardProps) {
  const copy = taskCopy[taskType];
  const draft = useCaseDraft(taskType, initialCaseState, onSubmit);
  const formState = draft.formState;
  const fields = formState?.fields || initialCaseState?.fields || [];
  const missing = formState?.missing_facts || initialCaseState?.missing_facts || [];

  useEffect(() => {
    onDraftChange?.(draft.facts, draft.statuses, formState);
  }, [draft.facts, draft.statuses, formState, onDraftChange]);

  if (!active) {
    return (
      <section className="mt-4 rounded-xl border border-[#d9e1df] bg-[#f7faf8] p-4" aria-label={copy.title}>
        <div className="flex items-center gap-2 text-sm font-semibold text-[#172033]"><Icon className="text-[#006a63]" name="scale" size={17} />{copy.title}</div>
        <p className="mt-2 text-xs leading-5 text-[#667085]">Thông tin đã dùng: {initialCaseState?.completed_count ?? 0}/{initialCaseState?.required_count ?? fields.filter((field) => field.required).length}</p>
        {missing.length > 0 && <p className="mt-1 text-xs text-[#9a5b18]">Còn thiếu: {missing.map((key) => factLabels[key] || key).join(', ')}.</p>}
      </section>
    );
  }

  const validationErrors = formState?.validation_errors || initialCaseState?.validation_errors || {};
  const requiredCount = formState?.required_count ?? initialCaseState?.required_count ?? fields.filter((field) => field.required).length;
  const completedCount = formState?.completed_count ?? initialCaseState?.completed_count ?? 0;
  const isBusy = draft.status === 'resolving' || draft.status === 'submitting';

  return (
    <section className="mt-4 rounded-xl border border-[#b9ddd7] bg-[#f7fcfb] p-4 sm:p-5" aria-label={copy.title}>
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#dff3ef] text-[#006a63]"><Icon name="scale" size={19} /></span>
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold text-[#172033]">{copy.title}</h3>
          <p className="mt-1 text-sm leading-6 text-[#53615e]">{copy.description}</p>
          <p className="mt-2 text-xs font-semibold text-[#006a63]">{missing.length ? `Còn thiếu ${missing.length} thông tin` : `${completedCount}/${requiredCount} thông tin đã có`}</p>
        </div>
      </div>
      {fields.length > 0 ? (
        <div className="mt-4">
          <CaseFieldList disabled={isBusy} fields={fields} onChange={draft.setFact} validationErrors={validationErrors} values={draft.facts} />
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-[#ead6b8] bg-[#fff8ea] p-3 text-sm text-[#714b18]">Đang chuẩn bị các thông tin cần cung cấp…</p>
      )}
      {draft.error && <p className="mt-3 rounded-lg border border-[#f0b7b2] bg-[#fff0ef] p-3 text-sm leading-6 text-[#7f1d1d]" role="alert">{draft.error}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button className="rounded-lg bg-[#0f766e] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#005c55] disabled:cursor-not-allowed disabled:bg-[#bdc9c6]" disabled={isBusy || !draft.isReady} onClick={() => void draft.submit()} type="button">
          {draft.status === 'submitting' ? 'Đang xử lý…' : copy.action}
        </button>
        {draft.dirty && <button className="rounded-lg border border-[#bdc9c6] bg-white px-3 py-2.5 text-sm font-semibold text-[#3e4947]" disabled={isBusy} onClick={draft.discard} type="button">Bỏ thay đổi</button>}
        {onOpenFullEditor && <button className="text-sm font-medium text-[#006a63] underline" onClick={onOpenFullEditor} type="button">Mở toàn bộ thông tin</button>}
      </div>
      <p className="mt-3 text-xs leading-5 text-[#667085]">Thông tin do bạn nhập được dùng để đối chiếu; trợ lý không xem đó là tài liệu đã được xác minh độc lập.</p>
    </section>
  );
}
