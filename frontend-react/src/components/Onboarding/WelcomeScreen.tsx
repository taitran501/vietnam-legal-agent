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
  suggestions: { title: string; prompt: string; icon: IconName }[];
}

export const legalGoals: LegalGoal[] = [
  {
    id: 'legality',
    icon: 'scale',
    label: 'Kiểm tra tính hợp pháp & Nghĩa vụ',
    intent: 'legal_lookup',
    placeholder: 'Mô tả hành vi, điều khoản hợp đồng hoặc nghĩa vụ cần kiểm tra đúng/sai luật…',
    suggestions: [
      {
        title: 'Trách nhiệm tái chế bao bì (EPR)',
        prompt: 'Cơ sở sản xuất, đóng gói hàng bằng túi nilon và chai nhựa có bắt buộc phải đóng tiền tái chế hay xử lý rác thải không?',
        icon: 'building',
      },
      {
        title: 'Thời gian thử việc và giữ lương',
        prompt: 'Công ty cho nhân viên thử việc 3 tháng và giữ lại một phần tiền lương thì có đúng quy định không?',
        icon: 'clock',
      },
      {
        title: 'Thỏa thuận phạt vi phạm hợp đồng',
        prompt: 'Trong hợp đồng mua bán, hai bên tự thỏa thuận mức phạt vi phạm 15% giá trị thì có hợp pháp không?',
        icon: 'fileText',
      },
      {
        title: 'Kinh doanh online & Thuế',
        prompt: 'Bán hàng qua mạng xã hội với quy mô nhỏ thì có bắt buộc phải đăng ký kinh doanh và đóng thuế không?',
        icon: 'scale',
      },
    ],
  },
  {
    id: 'procedure',
    icon: 'fileText',
    label: 'Hướng dẫn hồ sơ & Thủ tục',
    intent: 'compliance_checklist',
    placeholder: 'Nhập thủ tục hoặc giấy phép bạn cần thực hiện (làm sổ đỏ, mở quán, đăng ký thuế…)',
    suggestions: [
      {
        title: 'Cấp Sổ đỏ đất khai hoang',
        prompt: 'Đất gia đình khai hoang ở từ lâu nhưng chưa có giấy tờ thì các bước xin cấp Sổ đỏ lần đầu như thế nào?',
        icon: 'building',
      },
      {
        title: 'Giấy phép mở quán ăn / F&B',
        prompt: 'Tôi muốn mở một quán ăn thì cần chuẩn bị những giấy tờ gì và xin những giấy phép nào?',
        icon: 'checklist',
      },
      {
        title: 'Đăng ký người phụ thuộc giảm trừ gia cảnh',
        prompt: 'Thủ tục đăng ký người phụ thuộc (bố mẹ già, con nhỏ) để giảm tiền thuế thu nhập cá nhân cần giấy tờ gì?',
        icon: 'fileText',
      },
      {
        title: 'Lập di chúc nhà đất hợp pháp',
        prompt: 'Cách lập di chúc để lại nhà đất cho con cái hợp pháp để sau này không xảy ra tranh chấp.',
        icon: 'scale',
      },
    ],
  },
  {
    id: 'dispute',
    icon: 'shield',
    label: 'Bảo vệ quyền lợi & Tranh chấp',
    intent: 'protect_rights',
    placeholder: 'Mô tả vụ việc bị vi phạm, tranh chấp hoặc bị phạt bạn đang gặp phải…',
    suggestions: [
      {
        title: 'Bị cho thôi việc đột ngột',
        prompt: 'Tôi bị công ty cho thôi việc đột ngột không rõ lý do thì được đòi bồi thường và trợ cấp những khoản gì?',
        icon: 'scale',
      },
      {
        title: 'Tranh chấp tiền đặt cọc mua nhà',
        prompt: 'Tôi đặt cọc mua nhà nhưng bên bán đổi ý không bán và không chịu trả lại tiền cọc thì phải giải quyết thế nào?',
        icon: 'shield',
      },
      {
        title: 'Hết hợp đồng thuê nhà không chịu dọn',
        prompt: 'Hết hạn hợp đồng mà người thuê nhà không chịu dọn đi và không trả tiền nhà thì xử lý thế nào cho đúng luật?',
        icon: 'building',
      },
      {
        title: 'Khiếu nại biên bản xử phạt hành chính',
        prompt: 'Nếu bị cơ quan chức năng lập biên bản xử phạt mà thấy không thỏa đáng thì cần làm đơn khiếu nại ở đâu?',
        icon: 'alert',
      },
    ],
  },
];

export const defaultCards = [
  {
    category: 'Đất đai & Bất động sản',
    title: 'Cấp Sổ đỏ lần đầu',
    prompt: 'Thủ tục cấp Giấy chứng nhận quyền sử dụng đất (Sổ đỏ) lần đầu theo Luật Đất đai mới.',
    icon: 'building' as const,
    intent: 'legal_lookup',
  },
  {
    category: 'Lao động & Việc làm',
    title: 'Thời gian & Lương thử việc',
    prompt: 'Thời gian thử việc tối đa và mức lương thử việc theo quy định Bộ luật Lao động.',
    icon: 'clock' as const,
    intent: 'legal_lookup',
  },
  {
    category: 'Môi trường & Doanh nghiệp',
    title: 'Trách nhiệm tái chế (EPR)',
    prompt: 'Cơ sở sản xuất hàng hóa có bắt buộc phải đóng tiền tái chế bao bì rác thải không?',
    icon: 'scale' as const,
    intent: 'legal_lookup',
  },
  {
    category: 'Dân sự & Hợp đồng',
    title: 'Tranh chấp tiền đặt cọc',
    prompt: 'Bên bán không trả lại tiền đặt cọc mua nhà thì tôi phải khởi kiện ở đâu?',
    icon: 'shield' as const,
    intent: 'protect_rights',
  },
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

  const handlePrefill = (prompt: string, intent: string) => {
    onPrefillPrompt(prompt, intent);
    setPrefillRevision((revision) => revision + 1);
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
      <div className="mx-auto flex min-h-full w-full max-w-[860px] flex-col items-center px-4 pb-12 pt-[clamp(2.5rem,7vh,5rem)] sm:px-6">
        {/* Brand Icon & Heading */}
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-teal-50 text-[#006a63] ring-1 ring-teal-600/20 shadow-sm">
          <Icon name="scale" size={24} />
        </div>

        <h1 className="mt-5 text-center text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl lg:text-4xl">
          Trợ lý Pháp luật Việt Nam
        </h1>

        <p className="mt-2.5 max-w-[580px] text-center text-sm leading-relaxed text-slate-500 sm:text-[15px]">
          Tra cứu căn cứ pháp lý, tư vấn tình huống thực tế và hướng dẫn thủ tục từ hơn 84.900+ điều luật & Bộ Pháp điển Quốc gia.
        </p>

        {/* Central Chat Input */}
        <div className="mt-7 w-full max-w-[760px]">
          {guidedTask && onGuidedSubmit ? (
            <>
              <GuidedCaseCard onDraftChange={onGuidedDraftChange} onSubmit={onGuidedSubmit} taskType={guidedTask} />
              {onCancelGuided && (
                <button className="mx-auto mt-3 block text-sm font-semibold text-teal-700 hover:underline" onClick={onCancelGuided} type="button">
                  Quay lại tra cứu quy định
                </button>
              )}
            </>
          ) : (
            <>
              <ChatInput
                disabled={disabled}
                focusRequest={prefillRevision}
                intentLabel={intentLabel}
                isStreaming={isStreaming}
                onClearIntent={onClearIntent}
                onSend={onSendPrompt}
                onStop={onStop}
                onValueChange={onDraftChange}
                placeholder={activeGoal?.placeholder || 'Nhập câu hỏi hoặc mô tả tình huống pháp lý của bạn…'}
                value={draftText}
                variant="welcome"
              />

              {/* Goal Category Pills */}
              <div className="mt-3 flex flex-wrap justify-center gap-2" aria-label="Mục tiêu pháp lý">
                {legalGoals.map((goal) => {
                  const isSelected = selectedGoalId === goal.id;
                  return (
                    <button
                      className={cn(
                        'inline-flex min-h-8 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600',
                        isSelected
                          ? 'border-teal-600 bg-teal-50 font-semibold text-teal-800 shadow-sm ring-1 ring-teal-600'
                          : 'border-slate-200 bg-white text-slate-600 hover:border-teal-600/40 hover:bg-slate-50 hover:text-teal-900'
                      )}
                      disabled={isStreaming || disabled}
                      key={goal.id}
                      onClick={() => handleGoalClick(goal)}
                      type="button"
                    >
                      <Icon name={goal.icon} size={14} />
                      {goal.label}
                    </button>
                  );
                })}
              </div>

              {caseDisabled && caseDisabledReason && (
                <p className="mt-2 text-center text-xs leading-5 text-amber-800" id="case-capability-message" role="status">
                  {caseDisabledReason}
                </p>
              )}
            </>
          )}
        </div>

        {/* Minimalist Scenario Cards Grid (2x2) */}
        {!guidedTask && (
          <section className="mt-8 w-full max-w-[760px]" aria-labelledby="suggestion-title">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-600" id="suggestion-title">
                {activeGoal ? `Tình huống mẫu: ${activeGoal.label}` : 'Gợi ý tình huống pháp lý phổ biến'}
              </h2>
              {activeGoal && (
                <button
                  className="text-xs font-semibold text-teal-700 hover:underline"
                  onClick={() => setSelectedGoalId(null)}
                  type="button"
                >
                  Xem tất cả chủ đề
                </button>
              )}
            </div>

            {/* 2x2 Grid of scenario prompt cards */}
            <div className="grid gap-3 sm:grid-cols-2">
              {activeGoal
                ? activeGoal.suggestions.map((item) => (
                    <button
                      className="group flex flex-col items-start justify-between rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-all hover:border-teal-600/50 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600"
                      disabled={disabled || isStreaming}
                      key={item.prompt}
                      onClick={() => handlePrefill(item.prompt, activeGoal.intent)}
                      type="button"
                    >
                      <div className="flex w-full items-start justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-teal-700 group-hover:bg-teal-600 group-hover:text-white transition-colors">
                            <Icon name={item.icon} size={15} />
                          </span>
                          <span className="text-xs font-bold text-slate-900 group-hover:text-teal-800">
                            {item.title}
                          </span>
                        </div>
                        <Icon className="text-slate-300 group-hover:text-teal-600 transition-colors" name="chevronRight" size={15} />
                      </div>
                      <p className="mt-2 text-xs leading-relaxed text-slate-600 group-hover:text-slate-800">
                        {item.prompt}
                      </p>
                    </button>
                  ))
                : defaultCards.map((card) => (
                    <button
                      className="group flex flex-col items-start justify-between rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-all hover:border-teal-600/50 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600"
                      disabled={disabled || isStreaming}
                      key={card.prompt}
                      onClick={() => handlePrefill(card.prompt, card.intent)}
                      type="button"
                    >
                      <div className="flex w-full items-start justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-teal-700 group-hover:bg-teal-600 group-hover:text-white transition-colors">
                            <Icon name={card.icon} size={15} />
                          </span>
                          <div>
                            <span className="block text-[10px] font-semibold uppercase tracking-wider text-teal-700">
                              {card.category}
                            </span>
                            <span className="text-xs font-bold text-slate-900 group-hover:text-teal-800">
                              {card.title}
                            </span>
                          </div>
                        </div>
                        <Icon className="text-slate-300 group-hover:text-teal-600 transition-colors" name="chevronRight" size={15} />
                      </div>
                      <p className="mt-2 text-xs leading-relaxed text-slate-600 group-hover:text-slate-800">
                        {card.prompt}
                      </p>
                    </button>
                  ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
