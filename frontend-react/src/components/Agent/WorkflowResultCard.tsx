import type { WorkflowMetadata } from '@/types';

interface WorkflowResultCardProps {
  workflow?: WorkflowMetadata;
}

export function WorkflowResultCard({ workflow }: WorkflowResultCardProps) {
  if (!workflow) return null;
  const safeStop = ['insufficient_evidence', 'out_of_scope', 'citation_verification_failed'].includes(
    workflow.termination_reason || ''
  );
  const hasAssessment = Boolean(workflow.assessment);
  const hasChecklist = Boolean(workflow.checklist?.length);
  const hasMissingFacts = Boolean(workflow.missing_facts?.length);

  const hasCitations = Boolean(workflow.citations?.length);
  if (!safeStop && !hasAssessment && !hasChecklist && !hasMissingFacts && !hasCitations) return null;

  return (
    <section className="mt-4 space-y-3" aria-label="Kết quả workflow">
      {hasMissingFacts && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          <p className="font-semibold">Cần bổ sung thông tin</p>
          <p className="mt-1">Hoàn thiện các trường được đánh dấu trong Hồ sơ trường hợp trước khi hệ thống kết luận.</p>
        </div>
      )}
      {safeStop && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-950">
          <p className="font-semibold">Hệ thống đã dừng an toàn</p>
          <p className="mt-1">Chưa có đủ bằng chứng được kiểm chứng để đưa ra kết luận pháp lý.</p>
        </div>
      )}
      {hasAssessment && (
        <div className="rounded-xl border border-teal-200 bg-teal-50/60 p-3 text-sm text-slate-800">
          <p className="font-semibold text-teal-950">Đánh giá sơ bộ</p>
          <p className="mt-1">Kết quả dựa trên facts đã cung cấp và các nguồn hiển thị bên dưới; không thay thế tư vấn pháp lý.</p>
        </div>
      )}
      {hasChecklist && (
        <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm text-slate-800">
          <p className="font-semibold">Checklist tuân thủ</p>
          <ol className="mt-2 list-decimal space-y-1.5 pl-5">
            {workflow.checklist?.map((item, index) => (
              <li key={index}>{String(item.item || item.action || 'Hạng mục cần thực hiện')}</li>
            ))}
          </ol>
        </div>
      )}
      {hasCitations && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
          <p className="font-semibold text-slate-900">Nguồn đã kiểm tra</p>
          <ul className="mt-1.5 space-y-1">
            {workflow.citations?.map((citation, index) => (
              <li key={index}>[{String(citation.index || index + 1)}] {String(citation.label || citation.document_id || 'Nguồn pháp lý')}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
