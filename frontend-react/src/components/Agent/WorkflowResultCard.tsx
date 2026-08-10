import type { WorkflowMetadata } from '@/types';
import { Icon } from '@/components/UI/Icon';
import { TraceDrawer } from './TraceDrawer';

interface WorkflowResultCardProps {
  onOpenCase?: () => void;
  onResearch?: () => void;
  workflow?: WorkflowMetadata;
}

const missingFactLabels: Record<string, string> = {
  business_role: 'vai trò doanh nghiệp',
  product_or_packaging: 'sản phẩm hoặc bao bì',
  material: 'vật liệu chính',
  activity_scope: 'phạm vi hoạt động',
  object_kind: 'loại đối tượng',
  product_group: 'nhóm sản phẩm EPR',
  packaged_goods_category: 'nhóm hàng hóa được đóng gói',
  market_placement: 'phạm vi đưa ra thị trường',
  activity_purpose: 'mục đích hoạt động',
  annual_revenue_vnd: 'doanh thu liên quan',
  reused_by_producer: 'trường hợp thu hồi và tái sử dụng bao bì',
  recovery_rate: 'tỷ lệ thu hồi và tái sử dụng',
};

export function WorkflowResultCard({ onOpenCase, onResearch, workflow }: WorkflowResultCardProps) {
  if (!workflow) return null;
  const safeStop = ['insufficient_evidence', 'out_of_scope', 'citation_verification_failed'].includes(
    workflow.termination_reason || ''
  );
  const completedDecision = workflow.outcome === 'completed'
    && ['likely_in_scope', 'likely_out_of_scope'].includes(String(workflow.assessment?.status || ''));
  const hasAssessment = (workflow.result_type === 'assessment' && completedDecision)
    || (!workflow.outcome && !workflow.result_type && Boolean(workflow.assessment));
  const hasChecklist = (
    (workflow.result_type === 'checklist' && workflow.outcome === 'completed')
    || (!workflow.outcome && !workflow.result_type)
  ) && Boolean(workflow.checklist?.length);
  const hasMissingFacts = Boolean(workflow.missing_facts?.length);
  const hasAssumptions = Boolean(workflow.assumptions?.length);

  const hasTrace = import.meta.env.VITE_ENABLE_TRACE_DEBUG === 'true' && Boolean(workflow.trace_id);
  if (!safeStop && !hasAssessment && !hasChecklist && !hasMissingFacts && !hasAssumptions && !hasTrace) return null;

  return (
    <section className="mt-5 space-y-3" aria-label="Kết quả workflow">
      {hasMissingFacts && (
        <div className="rounded-lg border border-[#cad5ec] bg-[#f3f6fc] p-4 text-sm text-[#29354b]">
          <div className="flex items-start gap-3">
            <Icon className="mt-0.5 shrink-0 text-[#555e74]" name="info" size={19} />
            <div className="min-w-0 flex-1">
              <p className="font-semibold">Cần thêm thông tin để tiếp tục</p>
              <p className="mt-1 leading-6">
                Vui lòng bổ sung {workflow.missing_facts?.map((fact) => missingFactLabels[fact] || fact).join(', ')}.
              </p>
              {onOpenCase && (
                <button
                  className="mt-3 inline-flex items-center gap-2 rounded-md bg-[#555e74] px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-[#3e475b] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#555e74] focus-visible:ring-offset-2"
                  onClick={onOpenCase}
                  type="button"
                >
                  <Icon name="case" size={15} />
                  Bổ sung trong bảng thông tin
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {safeStop && (
        <div className="rounded-lg border border-[#ead6b8] bg-[#fff8ea] p-4 text-sm text-[#714b18]">
          <div className="flex items-start gap-3">
            <Icon className="mt-0.5 shrink-0" name="alert" size={19} />
            <div>
              <p className="font-semibold">Chưa đủ căn cứ để trả lời chắc chắn</p>
              <p className="mt-1 leading-6">
                Trợ lý đã dừng để tránh đưa ra kết luận không được nguồn hiện có hỗ trợ. Bạn có thể thu hẹp câu hỏi hoặc thử lại sau.
              </p>
              {workflow.available_actions?.includes('research_web') && onResearch && (
                <button
                  className="mt-3 rounded-md border border-[#ad7b36] bg-white px-3 py-2 text-xs font-semibold text-[#714b18] hover:bg-[#fff1d7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ad7b36]"
                  onClick={onResearch}
                  type="button"
                >
                  Tìm nguồn công khai
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {hasAssessment && (
        <div className="rounded-lg border border-[#b9ddd7] bg-[#f0faf8] p-4 text-sm text-[#254b47]">
          <div className="flex items-start gap-3">
            <Icon className="mt-0.5 shrink-0 text-[#006a63]" name="scale" size={19} />
            <div>
              <p className="font-semibold text-[#005c55]">Đánh giá sơ bộ</p>
              <p className="mt-1 leading-6">
                Kết quả dựa trên thông tin đã cung cấp và các nguồn hiển thị cùng câu trả lời; không thay thế tư vấn pháp lý.
              </p>
            </div>
          </div>
        </div>
      )}

      {hasChecklist && (
        <div className="rounded-lg border border-[#d9e1df] bg-white p-4 text-sm text-[#3e4947]">
          <div className="flex items-center gap-2 font-semibold text-[#172033]">
            <Icon className="text-[#006a63]" name="check" size={18} />
            Checklist đề xuất
          </div>
          <ol className="mt-3 space-y-2.5">
            {workflow.checklist?.map((item, index) => (
              <li className="flex items-start gap-2.5 leading-6" key={index}>
                <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-[#80d5cb] text-[10px] font-semibold text-[#006a63]">
                  {index + 1}
                </span>
                <span>{String(item.item || item.action || 'Hạng mục cần thực hiện')}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {hasAssumptions && (
        <details className="rounded-lg border border-[#d9e1df] bg-[#f7faf8] px-4 py-3 text-sm text-[#53615e]">
          <summary className="cursor-pointer font-semibold text-[#3e4947]">Giả định đang sử dụng</summary>
          <ul className="mt-2 list-disc space-y-1.5 pl-5 leading-6">
            {workflow.assumptions?.map((assumption, index) => <li key={index}>{assumption}</li>)}
          </ul>
        </details>
      )}
      <TraceDrawer traceId={workflow.trace_id} />
    </section>
  );
}
