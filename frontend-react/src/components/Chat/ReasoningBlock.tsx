import { useState } from 'react';
import type { WorkflowStep } from '@/types';
import { Icon } from '@/components/UI/Icon';

interface ReasoningBlockProps {
  isStreaming?: boolean;
  statusMessage?: string;
  steps?: WorkflowStep[];
  defaultExpanded?: boolean;
}

const STEP_LABELS: Record<string, string> = {
  validate_input: 'Kiểm tra tính hợp lệ của câu hỏi',
  load_context: 'Nạp lịch sử & ngữ cảnh vụ việc',
  classify_route: 'Xác định quan hệ pháp luật & nhánh luật',
  lookup_answer_cache: 'Kiểm tra kho giải đáp đã thẩm định',
  search_legal_provisions: 'Truy xuất điều khoản trong 84.900+ điều luật',
  evaluate_legal_case: 'Áp dụng quy tắc pháp lý & đối chiếu điều kiện',
  calculate_statutory_amounts: 'Tính toán chế độ, tiền lương, bồi thường luật định',
  search_web_official: 'Tra cứu bổ sung từ Cổng TTĐT Bộ/Ngành',
  evaluate_evidence: 'Đánh giá độ tin cậy của tài liệu trích dẫn',
  compose_answer: 'Soạn thảo nội dung tư vấn pháp lý',
  verify_citations: 'Thẩm định phản biện & rà soát hiệu lực văn bản',
  critic_review: 'Hội đồng phản biện cao cấp duyệt câu trả lời',
  finish: 'Hoàn tất quy trình xử lý',
};

export function ReasoningBlock({
  isStreaming = false,
  statusMessage,
  steps = [],
  defaultExpanded,
}: ReasoningBlockProps) {
  const [isOpen, setIsOpen] = useState(defaultExpanded ?? isStreaming);

  const displaySteps = steps.filter((step) => Boolean(step.action));
  const currentStep = displaySteps[displaySteps.length - 1];
  const activeLabel =
    statusMessage ||
    (currentStep ? STEP_LABELS[currentStep.action] || currentStep.label : 'Đang phân tích yêu cầu pháp lý…');

  const stepCount = displaySteps.length;

  return (
    <div className="my-2.5 overflow-hidden rounded-xl border border-slate-200/80 bg-slate-50/70 text-xs text-slate-600 transition-all">
      {/* Header bar / Toggle */}
      <button
        className="flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left font-medium text-slate-700 transition-colors hover:bg-slate-100/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600"
        onClick={() => setIsOpen((prev) => !prev)}
        type="button"
      >
        <div className="flex min-w-0 items-center gap-2">
          {isStreaming ? (
            <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal-400 opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-teal-600" />
            </span>
          ) : (
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-teal-100 text-teal-700">
              <Icon name="check" size={11} />
            </span>
          )}

          <span className="truncate font-semibold text-slate-800">
            {isStreaming
              ? activeLabel
              : `Đã đối chiếu & suy luận qua ${stepCount > 0 ? `${stepCount} bước` : 'các bước pháp lý'}`}
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
          <span>{isOpen ? 'Thu gọn' : 'Xem tiến trình'}</span>
          <Icon
            className={`transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
            name="chevronDown"
            size={13}
          />
        </div>
      </button>

      {/* Expanded Step Trace */}
      {isOpen && (
        <div className="border-t border-slate-200/60 bg-white/60 px-3.5 py-2.5">
          <ol className="relative space-y-2 border-l border-slate-200 pl-3">
            {displaySteps.map((step, idx) => {
              const label = STEP_LABELS[step.action] || step.label || step.action;
              const isLast = idx === displaySteps.length - 1;
              const isCompleted = !isStreaming || !isLast;

              return (
                <li className="relative flex items-start gap-2" key={`${step.step}-${step.action}-${idx}`}>
                  <span
                    className={`absolute -left-[17px] top-1 h-2 w-2 rounded-full ring-2 ring-white ${
                      isCompleted ? 'bg-teal-500' : 'animate-pulse bg-amber-500'
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className={`text-[12px] leading-tight ${isCompleted ? 'text-slate-700' : 'font-semibold text-teal-900'}`}>
                      {label}
                    </p>
                    {Boolean(step.details) && (
                      <p className="mt-0.5 text-[11px] text-slate-600">
                        {String(step.details)}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}

            {isStreaming && (
              <li className="relative flex items-start gap-2">
                <span className="absolute -left-[17px] top-1 h-2 w-2 animate-ping rounded-full bg-teal-400 ring-2 ring-white" />
                <p className="text-[12px] font-medium text-teal-800">
                  {activeLabel}
                </p>
              </li>
            )}
          </ol>
        </div>
      )}
    </div>
  );
}
