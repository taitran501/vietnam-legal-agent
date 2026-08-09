import type { WorkflowStep } from '@/types';

const labels: Record<string, string> = {
  load_context: 'Nạp ngữ cảnh',
  understand_task: 'Xác định yêu cầu',
  check_cache: 'Kiểm tra câu trả lời đã xác minh',
  answer_cache: 'Dùng câu trả lời đã xác minh',
  ask_user: 'Yêu cầu thông tin còn thiếu',
  retrieve_faq: 'Tra FAQ',
  retrieve_legal: 'Tra cứu văn bản pháp luật',
  retrieve_web: 'Tra cứu nguồn EPR bổ sung',
  evaluate_evidence: 'Đánh giá bằng chứng',
  compose_answer: 'Soạn kết quả',
  verify_citations: 'Kiểm tra trích dẫn',
  repair_answer: 'Sửa câu trả lời theo nguồn',
  finish: 'Hoàn tất',
  safe_stop: 'Dừng an toàn',
};

interface WorkflowTimelineProps {
  steps: WorkflowStep[];
  isStreaming: boolean;
}

export function WorkflowTimeline({ steps, isStreaming }: WorkflowTimelineProps) {
  if (!isStreaming && steps.length === 0) return null;

  return (
    <section className="mx-auto mb-3 w-full max-w-4xl px-4" aria-label="Tiến trình xử lý">
      <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">Tiến trình xử lý</p>
          {isStreaming && <span className="text-xs text-teal-700">Đang chạy…</span>}
        </div>
        <ol className="flex gap-2 overflow-x-auto pb-1">
          {steps.map((step) => (
            <li key={`${step.step}-${step.action}`} className="flex shrink-0 items-center gap-1.5 text-xs text-slate-600">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-teal-700 text-[10px] font-semibold text-white">
                {step.step}
              </span>
              <span>{labels[step.action] || step.action}</span>
            </li>
          ))}
          {isStreaming && steps.length === 0 && <li className="text-xs text-slate-500">Đang chuẩn bị ngữ cảnh…</li>}
        </ol>
      </div>
    </section>
  );
}
