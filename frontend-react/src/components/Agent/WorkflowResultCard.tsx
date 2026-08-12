import type { WorkflowMetadata } from '@/types';
import { Icon } from '@/components/UI/Icon';
import { TraceDrawer } from './TraceDrawer';

interface WorkflowResultCardProps {
  onOpenCase?: () => void;
  onOpenSources?: () => void;
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

export function WorkflowResultCard({ onOpenCase, onOpenSources, onResearch, workflow }: WorkflowResultCardProps) {
  if (!workflow) return null;
  const rawStopReason = workflow.safe_stop_reason || workflow.citation_error || workflow.termination_reason || '';
  const stopKey = ({
    insufficient_evidence: 'insufficient_evidence',
    explicit_no_evidence_signal: 'missing_provision',
    outside_registered_corpus: 'out_of_scope',
    citation_verification_failed: 'failed_citation_verification',
    unavailable_dependency: 'unavailable_dependencies',
    stale_corpus: 'stale_corpus',
  } as Record<string, string>)[rawStopReason] || rawStopReason;
  const safeStop = ['insufficient_evidence', 'missing_provision', 'incomplete_issue_coverage', 'failed_citation_verification', 'out_of_scope', 'stale_corpus', 'unavailable_dependencies', 'invalid_or_unresolved_fact'].includes(stopKey);
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
  const stopDetails: Record<string, { title: string; message: string }> = {
    out_of_scope: { title: 'Ngoài phạm vi hỗ trợ', message: 'Yêu cầu này không thuộc kho pháp luật EPR đã đăng ký.' },
    insufficient_evidence: { title: 'Chưa đủ căn cứ để trả lời chắc chắn', message: 'Một hoặc nhiều vấn đề bắt buộc chưa có nguồn hoạt động phù hợp để kiểm chứng.' },
    missing_provision: { title: 'Chưa tìm thấy điều khoản phù hợp', message: 'Kho pháp luật hiện tại chưa có nguồn hoạt động đủ cụ thể cho yêu cầu này.' },
    incomplete_issue_coverage: { title: 'Chưa đủ căn cứ cho toàn bộ vấn đề', message: 'Một hoặc nhiều vấn đề bắt buộc chưa có nguồn hoạt động phù hợp để kiểm chứng.' },
    failed_citation_verification: { title: 'Không xác minh được trích dẫn', message: 'Câu trả lời đã được dừng vì nguồn hoặc vị trí trích dẫn chưa vượt qua kiểm tra.' },
    stale_corpus: { title: 'Corpus cần cập nhật', message: 'Dữ liệu pháp luật hiện tại chưa được xác nhận là mới nhất cho chuỗi sửa đổi.' },
    unavailable_dependencies: { title: 'Một dịch vụ đang tạm thời không khả dụng', message: 'Hãy thử lại sau; hệ thống chưa đưa ra kết luận khi phụ thuộc cần thiết chưa sẵn sàng.' },
    invalid_or_unresolved_fact: { title: 'Thông tin chưa đủ rõ để kết luận', message: 'Một giá trị chưa hợp lệ hoặc thuộc nhóm chưa được xác định trong rule pack hiện tại.' },
  };
  const stop = stopDetails[stopKey] || {
    title: 'Workflow đã dừng an toàn',
    message: 'Trợ lý đã dừng để tránh đưa ra kết luận không được nguồn hiện có hỗ trợ.',
  };

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
              <p className="font-semibold">{stop.title}</p>
              <p className="mt-1 leading-6">{stop.message} Bạn có thể thu hẹp câu hỏi hoặc thử lại sau.</p>
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
              <p className="mt-1 font-semibold leading-6">{String(workflow.assessment?.conclusion || 'Đã có kết quả đánh giá.')}</p>
              {!!workflow.assessment?.reasons && <ul className="mt-2 list-disc space-y-1 pl-5">{(workflow.assessment.reasons as Array<Record<string, unknown>>).map((reason, index) => <li key={index}>{String(reason.claim || '')}</li>)}</ul>}
              {!!workflow.assessment?.next_steps && <p className="mt-2 leading-6"><span className="font-semibold">Bước tiếp theo:</span> {(workflow.assessment.next_steps as string[]).join(' ')}</p>}
              <p className="mt-2 text-xs">Kết quả dựa trên thông tin đã cung cấp và nguồn hiển thị; không thay thế tư vấn pháp lý.</p>
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
                <span><span className="font-medium">{String(item.item || 'Hạng mục cần thực hiện')}</span>{typeof item.action === 'string' && item.action && <span className="block text-xs text-[#667085]">{item.action}</span>}{Array.isArray(item.evidence_indices) && item.evidence_indices.length > 0 && (onOpenSources ? <button className="block text-left text-xs text-[#006a63] underline" onClick={onOpenSources} type="button">Căn cứ: {(item.evidence_indices as unknown[]).map((value) => `[${String(value)}]`).join(' ')}</button> : <span className="block text-xs text-[#006a63]">Căn cứ: {(item.evidence_indices as unknown[]).map((value) => `[${String(value)}]`).join(' ')}</span>)}</span>
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
      <p className="text-[11px] text-[#667085]">Corpus pháp luật tính đến: {workflow.corpus_as_of_date || 'chưa được pháp lý phê duyệt'}</p>
      <TraceDrawer traceId={workflow.trace_id} />
    </section>
  );
}
