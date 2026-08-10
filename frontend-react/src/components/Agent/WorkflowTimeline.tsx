import { useEffect, useState } from 'react';
import type { WorkflowStep } from '@/types';
import { Icon } from '@/components/UI/Icon';

const labels: Record<string, string> = {
  load_context: 'Nạp ngữ cảnh',
  understand_task: 'Hiểu yêu cầu',
  check_cache: 'Kiểm tra câu trả lời đã có',
  answer_cache: 'Dùng câu trả lời đã xác minh',
  ask_user: 'Cần thêm thông tin',
  retrieve_legal: 'Tìm văn bản liên quan',
  retrieve_web: 'Tìm nguồn bổ sung',
  evaluate_evidence: 'Đánh giá bằng chứng',
  compose_answer: 'Soạn câu trả lời',
  verify_citations: 'Kiểm tra trích dẫn',
  repair_answer: 'Đối chiếu lại câu trả lời',
  finish: 'Hoàn tất',
  safe_stop: 'Dừng an toàn',
};

interface WorkflowTimelineProps {
  isStreaming: boolean;
  statusMessage?: string;
  steps: WorkflowStep[];
}

export function WorkflowTimeline({ isStreaming, statusMessage, steps }: WorkflowTimelineProps) {
  const [expanded, setExpanded] = useState(false);
  const current = steps[steps.length - 1];

  useEffect(() => {
    if (isStreaming) setExpanded(false);
  }, [isStreaming]);

  if (!isStreaming && steps.length === 0) return null;

  const currentLabel = current?.label || (current ? labels[current.action] || current.action : statusMessage || 'Đang chuẩn bị ngữ cảnh');
  const completedSummary = steps.length
    ? `Đã hoàn tất ${steps.length} bước · ${currentLabel}`
    : 'Đã hoàn tất xử lý';

  return (
    <section className="shrink-0 border-b border-[#e5e9e7] bg-[#f7faf8]" aria-label="Tiến trình xử lý">
      <div className="mx-auto w-full max-w-[820px] px-4 py-2.5 sm:px-6">
        <button
          aria-expanded={expanded}
          className="flex w-full items-center gap-2 text-left text-xs text-[#53615e] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]"
          onClick={() => setExpanded((value) => !value)}
          type="button"
        >
          {isStreaming ? (
            <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-[#80d5cb] border-t-[#006a63] motion-reduce:animate-none" />
          ) : (
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[#dff3ef] text-[#006a63]">
              <Icon name="check" size={11} />
            </span>
          )}
          <span aria-live="polite" className="min-w-0 flex-1 truncate font-medium text-[#3e4947]">
            {isStreaming ? currentLabel : completedSummary}
          </span>
          <Icon className={`transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} name="chevronDown" size={15} />
        </button>
        {expanded && (
          <ol className="mt-2 flex gap-1.5 overflow-x-auto pb-1">
            {steps.map((step) => (
              <li
                className="flex shrink-0 items-center gap-1.5 rounded-full border border-[#d9e1df] bg-white px-2.5 py-1 text-[11px] text-[#53615e]"
                key={`${step.step}-${step.action}`}
              >
                <span className="font-semibold text-[#006a63]">{step.step}</span>
                <span>{labels[step.action] || step.action}</span>
              </li>
            ))}
            {steps.length === 0 && <li className="text-[11px] text-[#667085]">Đang chuẩn bị ngữ cảnh…</li>}
          </ol>
        )}
      </div>
    </section>
  );
}
