import { useState } from 'react';
import { ChatInput } from '@/components/Chat/ChatInput';
import { Icon, type IconName } from '@/components/UI/Icon';
import { GuidedCaseCard } from '@/components/Case/GuidedCaseCard';
import type { CaseState } from '@/types';
import { eprPlainName, taskCopy } from '@/lib/userCopy';
import type { CaseFormState } from '@/types';

interface WelcomeScreenProps {
  disabled?: boolean;
  isStreaming: boolean;
  onSendPrompt: (prompt: string) => void;
  onPrefillPrompt: (prompt: string, intent: string) => void;
  draftText: string;
  onDraftChange: (value: string) => void;
  intentLabel?: string;
  onClearIntent: () => void;
  onStop: () => void;
  onStartCase?: (taskType: CaseState['task_type']) => void;
  guidedTask?: CaseState['task_type'] | null;
  onGuidedSubmit?: (facts: Record<string, string>, statuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>, taskType: CaseState['task_type']) => Promise<void>;
  onGuidedDraftChange?: (facts: Record<string, string>, statuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>, formState: CaseFormState | null) => void;
  onCancelGuided?: () => void;
  caseDisabled?: boolean;
  caseDisabledReason?: string;
}

const actions: Array<{ icon: IconName; label: string; prompt: string; intent: string; taskType?: CaseState['task_type'] }> = [
  {
    icon: 'search',
    label: 'Tra cứu quy định',
    prompt: 'Điều 77 quy định gì về trách nhiệm tái chế?',
    intent: 'legal_lookup',
  },
  {
    icon: 'scale',
    label: taskCopy.assess_epr_obligation.title,
    prompt: '',
    intent: 'case_assessment',
    taskType: 'assess_epr_obligation',
  },
  {
    icon: 'check',
    label: taskCopy.build_compliance_checklist.title,
    prompt: '',
    intent: 'compliance_checklist',
    taskType: 'build_compliance_checklist',
  },
];

const suggestions = [
  'Doanh nghiệp nhập khẩu bao bì có thuộc đối tượng thực hiện EPR không?',
  'Giải thích Điều 77 về trách nhiệm tái chế sản phẩm, bao bì.',
  'Tôi cần chuẩn bị thông tin gì để lập danh sách việc cần làm?',
];

export function WelcomeScreen({ disabled = false, isStreaming, onSendPrompt, onPrefillPrompt, onStop, draftText, onDraftChange, intentLabel, onClearIntent, onStartCase, guidedTask = null, onGuidedSubmit, onGuidedDraftChange, onCancelGuided, caseDisabled = false, caseDisabledReason }: WelcomeScreenProps) {
  const [prefillRevision, setPrefillRevision] = useState(0);

  const handlePrefill = (prompt: string, intent: string) => {
    onPrefillPrompt(prompt, intent);
    setPrefillRevision((revision) => revision + 1);
  };

  const handleAction = (action: (typeof actions)[number]) => {
    if (action.taskType && onStartCase) {
      onStartCase(action.taskType);
      return;
    }
    handlePrefill(action.prompt, action.intent);
  };

  return (
    <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto bg-[#fcfcfa]">
      <div className="mx-auto flex min-h-full w-full max-w-[980px] flex-col items-center px-5 pb-10 pt-[clamp(3rem,9vh,7rem)] sm:px-8">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-[#d9e1df] bg-white text-[#006a63]">
          <Icon name="scale" size={24} />
        </div>
        <h2 className="font-serif-legal mt-6 max-w-[820px] text-center text-[clamp(2rem,4vw,2.75rem)] font-semibold leading-[1.25] tracking-[-0.02em] text-[#172033]">
          Hôm nay bạn muốn tìm hiểu vấn đề pháp lý nào?
        </h2>
        <p className="mt-3 max-w-[620px] text-center text-sm leading-6 text-[#667085] sm:text-base">
          Tra cứu quy định về {eprPlainName}, làm rõ nội dung và chuẩn bị bước tiếp theo với nguồn để đối chiếu.
        </p>
        <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-[#d9e1df] bg-[#f7faf8] px-3 py-1.5 text-xs font-medium text-[#53615e]">
          <span className="h-1.5 w-1.5 rounded-full bg-[#0f766e]" />
          Phạm vi: EPR — {eprPlainName}
        </div>

        <div className="mt-8 w-full max-w-[760px]">
          {guidedTask && onGuidedSubmit ? (
            <>
              <GuidedCaseCard onDraftChange={onGuidedDraftChange} onSubmit={onGuidedSubmit} taskType={guidedTask} />
              {onCancelGuided && <button className="mx-auto mt-3 block text-sm font-medium text-[#006a63] underline" onClick={onCancelGuided} type="button">Quay lại tra cứu quy định</button>}
            </>
          ) : (
            <>
              <ChatInput
                disabled={disabled}
                isStreaming={isStreaming}
                onSend={onSendPrompt}
                onStop={onStop}
                value={draftText}
                onValueChange={onDraftChange}
                intentLabel={intentLabel}
                onClearIntent={onClearIntent}
                focusRequest={prefillRevision}
                variant="welcome"
              />
              <div className="mt-3 flex flex-wrap justify-center gap-2" aria-label="Tác vụ gợi ý">
                {actions.map((action) => (
                  <button
                    className="inline-flex min-h-10 items-center gap-2 rounded-full border border-[#bdc9c6] bg-white px-3.5 py-2 text-xs font-medium text-[#3e4947] transition-colors hover:border-[#0f766e] hover:bg-[#f1f4f3] hover:text-[#005c55] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e] sm:text-sm"
                    disabled={isStreaming || (!action.taskType && disabled) || Boolean(action.taskType && caseDisabled)}
                    key={action.label}
                    onClick={() => handleAction(action)}
                    title={action.taskType && caseDisabled ? caseDisabledReason : undefined}
                    type="button"
                  >
                    <Icon name={action.icon} size={16} />
                    {action.label}
                  </button>
                ))}
              </div>
              <p className="mt-3 text-center text-xs leading-5 text-[#667085]">
                Câu trả lời sẽ hiển thị căn cứ và những thông tin còn cần kiểm tra.
              </p>
            </>
          )}
        </div>

        {!guidedTask && (
          <section className="mt-10 w-full max-w-[760px]" aria-labelledby="suggestion-title">
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[#667085]" id="suggestion-title">
                Gợi ý cho bạn
              </h3>
              <p className="text-right text-[11px] text-[#84908d]">Chọn một câu, chỉnh sửa nếu cần rồi bấm “Gửi câu hỏi”.</p>
            </div>
            <div className="divide-y divide-[#e1e6e4] overflow-hidden rounded-lg border border-[#d9e1df] bg-white">
              {suggestions.map((suggestion) => (
                <button
                  className="group flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left text-sm leading-5 text-[#3e4947] transition-colors hover:bg-[#f1f4f3] hover:text-[#172033] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#0f766e] sm:text-[15px]"
                  disabled={disabled || isStreaming}
                  key={suggestion}
                  onClick={() => handlePrefill(suggestion, 'auto')}
                  type="button"
                >
                  <Icon className="shrink-0 text-[#6e7977] group-hover:text-[#006a63]" name="message" size={17} />
                  <span className="flex-1">{suggestion}</span>
                  <Icon className="shrink-0 text-[#98a29f]" name="chevronRight" size={16} />
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
