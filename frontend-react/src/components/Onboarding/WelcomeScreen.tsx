import { useState } from 'react';
import { ChatInput } from '@/components/Chat/ChatInput';
import { Icon, type IconName } from '@/components/UI/Icon';
import { GuidedCaseCard } from '@/components/Case/GuidedCaseCard';
import type { CaseState, CaseFormState } from '@/types';
import { cn } from '@/lib/cn';

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
  onGuidedDraftChange?: (facts: Record<string, string>, statuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>, formState: CaseFormState | null, dirty: boolean) => void;
  onCancelGuided?: () => void;
  caseDisabled?: boolean;
  caseDisabledReason?: string;
}

export type LegalGoalId = 'legality' | 'procedure' | 'dispute';

export interface LegalGoal {
  id: LegalGoalId;
  icon: IconName;
  label: string;
  intent: string;
  placeholder: string;
  suggestions: string[];
}

export const legalGoals: LegalGoal[] = [
  {
    id: 'legality',
    icon: 'scale',
    label: 'Kiểm tra tính hợp pháp & Nghĩa vụ',
    intent: 'legal_lookup',
    placeholder: 'Mô tả hành vi, điều khoản hợp đồng hoặc nghĩa vụ bạn cần kiểm tra đúng/sai luật…',
    suggestions: [
      'Cơ sở sản xuất, đóng gói hàng bằng túi nilon và chai nhựa có bắt buộc phải đóng tiền tái chế hay xử lý rác thải không?',
      'Công ty cho nhân viên thử việc 3 tháng và giữ lại một phần tiền lương thì có đúng quy định không?',
      'Trong hợp đồng mua bán, hai bên tự thỏa thuận mức phạt vi phạm 15% giá trị thì có hợp pháp không?',
      'Bán hàng qua mạng xã hội với quy mô nhỏ thì có bắt buộc phải đăng ký kinh doanh và đóng thuế không?',
    ],
  },
  {
    id: 'procedure',
    icon: 'fileText',
    label: 'Hướng dẫn hồ sơ & Thủ tục',
    intent: 'compliance_checklist',
    placeholder: 'Nhập thủ tục hoặc giấy phép bạn cần thực hiện (làm sổ đỏ, mở quán, đăng ký thuế…)',
    suggestions: [
      'Đất gia đình khai hoang ở từ lâu nhưng chưa có giấy tờ thì các bước xin cấp Sổ đỏ lần đầu như thế nào?',
      'Tôi muốn mở một quán ăn thì cần chuẩn bị những giấy tờ gì và xin những giấy phép nào?',
      'Thủ tục đăng ký người phụ thuộc (bố mẹ già, con nhỏ) để giảm tiền thuế thu nhập cá nhân cần giấy tờ gì?',
      'Cách lập di chúc để lại nhà đất cho con cái hợp pháp để sau này không xảy ra tranh chấp.',
    ],
  },
  {
    id: 'dispute',
    icon: 'shield',
    label: 'Bảo vệ quyền lợi & Tranh chấp',
    intent: 'protect_rights',
    placeholder: 'Mô tả vụ việc bị vi phạm, tranh chấp hoặc bị phạt bạn đang gặp phải…',
    suggestions: [
      'Tôi bị công ty cho thôi việc đột ngột không rõ lý do thì được đòi bồi thường và trợ cấp những khoản gì?',
      'Tôi đặt cọc mua nhà nhưng bên bán đổi ý không bán và không chịu trả lại tiền cọc thì phải giải quyết thế nào?',
      'Hết hạn hợp đồng mà người thuê nhà không chịu dọn đi và không trả tiền nhà thì xử lý thế nào cho đúng luật?',
      'Nếu bị cơ quan chức năng lập biên bản xử phạt mà thấy không thỏa đáng thì cần làm đơn khiếu nại ở đâu?',
    ],
  },
];

export const actions = [
  {
    icon: 'search' as const,
    label: 'Tra cứu quy định',
    prompt: 'Điều 77 quy định gì về trách nhiệm tái chế?',
    intent: 'legal_lookup',
  },
  {
    icon: 'building' as const,
    label: 'Kiểm tra trường hợp của doanh nghiệp',
    taskType: 'assess_epr_obligation' as const,
  },
  {
    icon: 'checklist' as const,
    label: 'Tạo danh sách việc cần làm',
    taskType: 'build_compliance_checklist' as const,
  },
];

export const defaultSuggestions = [
  'Thủ tục cấp Giấy chứng nhận quyền sử dụng đất (Sổ đỏ) lần đầu theo Luật Đất đai mới.',
  'Thời gian thử việc tối đa và mức lương thử việc theo quy định Bộ luật Lao động.',
  'Cơ sở sản xuất hàng hóa có bắt buộc phải đóng tiền tái chế bao bì rác thải không?',
  'Bên bán không trả lại tiền đặt cọc mua nhà thì tôi phải khởi kiện ở đâu?',
];

export function WelcomeScreen({
  disabled = false,
  isStreaming,
  onSendPrompt,
  onPrefillPrompt,
  onStop,
  draftText,
  onDraftChange,
  intentLabel,
  onClearIntent,
  onStartCase,
  guidedTask = null,
  onGuidedSubmit,
  onGuidedDraftChange,
  onCancelGuided,
  caseDisabled = false,
  caseDisabledReason,
}: WelcomeScreenProps) {
  const [prefillRevision, setPrefillRevision] = useState(0);
  const [selectedGoalId, setSelectedGoalId] = useState<LegalGoalId | null>(null);

  const activeGoal = legalGoals.find((g) => g.id === selectedGoalId) ?? null;
  const currentSuggestions = activeGoal ? activeGoal.suggestions : defaultSuggestions;

  const handlePrefill = (prompt: string, intent: string) => {
    onPrefillPrompt(prompt, intent);
    setPrefillRevision((revision) => revision + 1);
  };

  const handleAction = (action: (typeof actions)[number]) => {
    if (action.taskType && onStartCase) {
      onStartCase(action.taskType);
      return;
    }
    if (action.prompt) {
      handlePrefill(action.prompt, action.intent);
    }
  };

  const handleGoalClick = (goal: LegalGoal) => {
    if (selectedGoalId === goal.id) {
      setSelectedGoalId(null);
    } else {
      setSelectedGoalId(goal.id);
    }
    setPrefillRevision((revision) => revision + 1);
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
        <p className="mt-3 max-w-[640px] text-center text-sm leading-6 text-[#667085] sm:text-base">
          Trợ lý tra cứu và giải đáp pháp luật Việt Nam (Đất đai, Lao động, Doanh nghiệp, Thuế, Dân sự, Môi trường...), làm rõ quyền lợi và đối chiếu căn cứ pháp lý chính thức.
        </p>
        <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-[#d9e1df] bg-[#f7faf8] px-3.5 py-1.5 text-xs font-medium text-[#53615e]">
          <span className="h-1.5 w-1.5 rounded-full bg-[#0f766e]" />
          Kho Dữ liệu: 84.900+ Điều luật & Bộ Pháp điển Quốc gia
        </div>

        <div className="mt-8 w-full max-w-[760px]">
          {guidedTask && onGuidedSubmit ? (
            <>
              <GuidedCaseCard onDraftChange={onGuidedDraftChange} onSubmit={onGuidedSubmit} taskType={guidedTask} />
              {onCancelGuided && (
                <button className="mx-auto mt-3 block text-sm font-medium text-[#006a63] underline" onClick={onCancelGuided} type="button">
                  Quay lại tra cứu quy định
                </button>
              )}
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
                placeholder={activeGoal?.placeholder}
                variant="welcome"
              />
              <div className="mt-3 flex flex-wrap justify-center gap-2" aria-label="Tác vụ gợi ý">
                {actions.map((action) => (
                  <button
                    aria-describedby={action.taskType && caseDisabled && caseDisabledReason ? 'case-capability-message' : undefined}
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
              <div className="mt-2 flex flex-wrap justify-center gap-2" aria-label="Mục tiêu pháp lý">
                {legalGoals.map((goal) => {
                  const isSelected = selectedGoalId === goal.id;
                  return (
                    <button
                      className={cn(
                        'inline-flex min-h-9 items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]',
                        isSelected
                          ? 'border-[#0f766e] bg-[#e7f4f1] font-semibold text-[#005c55] shadow-sm ring-1 ring-[#0f766e]'
                          : 'border-[#d9e1df] bg-[#f7faf8] text-[#53615e] hover:border-[#0f766e] hover:bg-white hover:text-[#005c55]'
                      )}
                      disabled={isStreaming || disabled}
                      key={goal.id}
                      onClick={() => handleGoalClick(goal)}
                      type="button"
                    >
                      <Icon name={goal.icon} size={15} />
                      {goal.label}
                    </button>
                  );
                })}
              </div>
              {caseDisabled && caseDisabledReason && (
                <p className="mt-3 text-center text-xs leading-5 text-[#9a5b18]" id="case-capability-message" role="status">
                  {caseDisabledReason}
                </p>
              )}
              <p className="mt-3 text-center text-xs leading-5 text-[#667085]">
                {activeGoal
                  ? `Đang xem các tình huống mẫu về: ${activeGoal.label}. Chọn một câu bên dưới hoặc gõ trực tiếp.`
                  : 'Câu trả lời sẽ hiển thị căn cứ pháp lý, trích dẫn nguồn luật và các bước thực hiện.'}
              </p>
            </>
          )}
        </div>

        {!guidedTask && (
          <section className="mt-10 w-full max-w-[760px]" aria-labelledby="suggestion-title">
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[#667085]" id="suggestion-title">
                {activeGoal ? `Tình huống mẫu: ${activeGoal.label}` : 'Gợi ý tình huống pháp lý phổ biến'}
              </h3>
              {activeGoal && (
                <button
                  className="text-[11px] font-medium text-[#006a63] hover:underline"
                  onClick={() => setSelectedGoalId(null)}
                  type="button"
                >
                  Xem tất cả chủ đề
                </button>
              )}
              {!activeGoal && (
                <p className="text-right text-[11px] text-[#84908d]">Chọn một câu, chỉnh sửa nếu cần rồi bấm “Gửi câu hỏi”.</p>
              )}
            </div>
            <div className="divide-y divide-[#e1e6e4] overflow-hidden rounded-lg border border-[#d9e1df] bg-white">
              {currentSuggestions.map((suggestion) => (
                <button
                  className="group flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left text-sm leading-5 text-[#3e4947] transition-colors hover:bg-[#f1f4f3] hover:text-[#172033] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#0f766e] sm:text-[15px]"
                  disabled={disabled || isStreaming}
                  key={suggestion}
                  onClick={() => handlePrefill(suggestion, activeGoal?.intent || 'auto')}
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
