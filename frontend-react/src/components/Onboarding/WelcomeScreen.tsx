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

export type LegalGoalId = 'legal_lookup' | 'case_assessment' | 'legal_explain_compare' | 'compliance_checklist';

export interface LegalGoal {
  id: LegalGoalId;
  icon: IconName;
  label: string;
  intent: string;
  template: string;
  placeholder: string;
  suggestions: { title: string; prompt: string; icon: IconName }[];
}

export const legalGoals: LegalGoal[] = [
  {
    id: 'legal_lookup',
    icon: 'search',
    label: 'Tra cứu quy định pháp luật',
    intent: 'legal_lookup',
    template: 'Tôi muốn tra cứu quy định pháp luật về [nội dung/vấn đề cần tìm], theo [tên văn bản nếu có]...',
    placeholder: 'Ví dụ: Mức phạt xe máy vượt đèn đỏ theo Nghị định 100...',
    suggestions: [
      {
        title: 'Phạt xe máy vượt đèn đỏ',
        prompt: 'Tôi đi xe máy vượt đèn đỏ thì bị phạt bao nhiêu tiền và có bị tước bằng lái không?',
        icon: 'alert',
      },
      {
        title: 'Cổ đông tối thiểu công ty CP',
        prompt: 'Thành lập công ty cổ phần thì cần tối thiểu bao nhiêu cổ đông sáng lập theo Luật Doanh nghiệp?',
        icon: 'building',
      },
      {
        title: 'Thời gian & Lương thử việc',
        prompt: 'Thời gian thử việc tối đa và mức lương thử việc theo quy định Bộ luật Lao động là bao nhiêu?',
        icon: 'clock',
      },
      {
        title: 'Trách nhiệm tái chế bao bì (EPR)',
        prompt: 'Cơ sở sản xuất, đóng gói hàng bằng túi nilon và chai nhựa có bắt buộc phải đóng tiền tái chế hay xử lý rác thải không?',
        icon: 'scale',
      },
    ],
  },
  {
    id: 'case_assessment',
    icon: 'scale',
    label: 'Kiểm tra tính hợp pháp & Nghĩa vụ',
    intent: 'case_assessment',
    template: 'Tình huống của tôi là: [mô tả sự việc thực tế]. Theo quy định pháp luật hiện hành, tôi có quyền/nghĩa vụ gì và xử lý thế nào?',
    placeholder: 'Mô tả vụ việc thực tế bạn đang gặp phải để đánh giá căn cứ và quyền lợi...',
    suggestions: [
      {
        title: 'Chủ nhà đòi tăng giá thuê 30%',
        prompt: 'Chủ nhà đòi tăng giá thuê nhà 30% giữa chừng có đúng luật không?',
        icon: 'building',
      },
      {
        title: 'Cho thôi việc không báo trước',
        prompt: 'Công ty cho tôi nghỉ việc ngay từ ngày mai không báo trước thì bồi thường thế nào?',
        icon: 'alert',
      },
      {
        title: 'Tranh chấp tiền đặt cọc mua nhà',
        prompt: 'Tôi đặt cọc mua nhà nhưng bên bán đổi ý không bán và không chịu trả lại tiền cọc thì phải giải quyết thế nào?',
        icon: 'shield',
      },
      {
        title: 'Đơn phương ly hôn & Nuôi con',
        prompt: 'Vợ chồng muốn đơn phương ly hôn thì thủ tục và quyền nuôi con dưới 36 tháng tuổi được pháp luật quy định thế nào?',
        icon: 'scale',
      },
    ],
  },
  {
    id: 'legal_explain_compare',
    icon: 'fileText',
    label: 'Giải thích & So sánh quy định',
    intent: 'legal_explain_compare',
    template: 'Giải thích và so sánh điểm khác biệt giữa [quy định A] và [quy định B] theo pháp luật Việt Nam...',
    placeholder: 'Ví dụ: So sánh hợp đồng lao động xác định thời hạn và không xác định thời hạn...',
    suggestions: [
      {
        title: 'So sánh HĐLĐ có/không thời hạn',
        prompt: 'So sánh hợp đồng lao động xác định thời hạn và không xác định thời hạn theo Bộ luật Lao động 2019.',
        icon: 'fileText',
      },
      {
        title: 'Đặt cọc khác gì Trả trước',
        prompt: 'Phân biệt tiền đặt cọc và tiền trả trước trong giao dịch mua bán nhà đất theo Bộ luật Dân sự.',
        icon: 'scale',
      },
      {
        title: 'Đơn phương chấm dứt vs Sa thải',
        prompt: 'Phân biệt người sử dụng lao động đơn phương chấm dứt hợp đồng lao động với hình thức kỷ luật sa thải.',
        icon: 'alert',
      },
      {
        title: 'Công ty TNHH vs Cổ phần',
        prompt: 'So sánh ưu và nhược điểm giữa Công ty TNHH 1 thành viên và Công ty Cổ phần khi khởi nghiệp.',
        icon: 'building',
      },
    ],
  },
  {
    id: 'compliance_checklist',
    icon: 'checklist',
    label: 'Hướng dẫn hồ sơ & Thủ tục',
    intent: 'compliance_checklist',
    template: 'Lập danh sách các bước và hồ sơ tài liệu cần chuẩn bị để thực hiện thủ tục [tên thủ tục]...',
    placeholder: 'Nhập thủ tục bạn cần thực hiện (cấp sổ đỏ, mở quán ăn, đăng ký thuế…)',
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
        title: 'Đăng ký người phụ thuộc thuế TNCN',
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
];

export const defaultCards = [
  {
    category: 'Dân sự & Hợp đồng',
    title: 'Chủ nhà tăng giá thuê 30%',
    prompt: 'Chủ nhà đòi tăng giá thuê nhà 30% giữa chừng có đúng luật không?',
    icon: 'building' as const,
    intent: 'case_assessment',
  },
  {
    category: 'Lao động & Việc làm',
    title: 'Thôi việc không báo trước',
    prompt: 'Công ty cho tôi nghỉ việc ngay từ ngày mai không báo trước thì bồi thường thế nào?',
    icon: 'alert' as const,
    intent: 'case_assessment',
  },
  {
    category: 'Giao thông đường bộ',
    title: 'Xe máy vượt đèn đỏ',
    prompt: 'Tôi đi xe máy vượt đèn đỏ thì bị phạt bao nhiêu tiền và có bị tước bằng lái không?',
    icon: 'scale' as const,
    intent: 'legal_lookup',
  },
  {
    category: 'Hôn nhân & Gia đình',
    title: 'Ly hôn & Quyền nuôi con',
    prompt: 'Vợ chồng muốn đơn phương ly hôn thì thủ tục và quyền nuôi con dưới 36 tháng tuổi được pháp luật quy định thế nào?',
    icon: 'scale' as const,
    intent: 'case_assessment',
  },
  {
    category: 'Doanh nghiệp & Đầu tư',
    title: 'Cổ đông tối thiểu công ty CP',
    prompt: 'Thành lập công ty cổ phần thì cần tối thiểu bao nhiêu cổ đông sáng lập theo Luật Doanh nghiệp?',
    icon: 'building' as const,
    intent: 'legal_lookup',
  },
  {
    category: 'Môi trường & Doanh nghiệp',
    title: 'Trách nhiệm tái chế (EPR)',
    prompt: 'Cơ sở sản xuất hàng hóa có bắt buộc phải đóng tiền tái chế bao bì rác thải không?',
    icon: 'scale' as const,
    intent: 'legal_lookup',
  },
];

export function WelcomeScreen({
  disabled = false,
  isStreaming,
  onSendPrompt,
  onPrefillPrompt,
  onStop,
  onStartCase,
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
      onPrefillPrompt(goal.template, goal.intent);
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
                {onStartCase && (
                  <>
                    <button
                      aria-describedby={caseDisabled ? 'case-capability-message' : undefined}
                      className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-teal-200 bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-800 transition-all hover:border-teal-600/50 hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={isStreaming || disabled || caseDisabled}
                      onClick={() => onStartCase('assess_epr_obligation')}
                      type="button"
                    >
                      <Icon name="case" size={14} />
                      Kiểm tra trường hợp của doanh nghiệp
                    </button>
                    <button
                      aria-describedby={caseDisabled ? 'case-capability-message' : undefined}
                      className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-teal-200 bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-800 transition-all hover:border-teal-600/50 hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={isStreaming || disabled || caseDisabled}
                      onClick={() => onStartCase('build_compliance_checklist')}
                      type="button"
                    >
                      <Icon name="checklist" size={14} />
                      Tạo danh sách việc cần làm
                    </button>
                  </>
                )}
              </div>

              {activeGoal && (
                <div className="mt-3 flex items-center justify-between rounded-lg border border-teal-200/80 bg-teal-50/70 px-3.5 py-2 text-xs text-teal-900 shadow-xs">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <Icon name="check" size={14} className="text-teal-700 shrink-0" />
                    <span className="truncate">
                      Đã điền khung câu hỏi mẫu <strong>{activeGoal.label}</strong> vào ô chat. Bạn hãy sửa đổi nội dung và bấm gửi.
                    </span>
                  </div>
                  <button
                    className="ml-2 shrink-0 font-semibold text-teal-800 underline hover:text-teal-950"
                    onClick={() => onPrefillPrompt(activeGoal.template, activeGoal.intent)}
                    type="button"
                  >
                    Điền lại mẫu
                  </button>
                </div>
              )}

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
