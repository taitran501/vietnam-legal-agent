import type { WorkflowMetadata } from '@/types';
import { Icon } from '@/components/UI/Icon';
import { TraceDrawer } from './TraceDrawer';
import { GuidedCaseCard } from '@/components/Case/GuidedCaseCard';
import type { CaseState } from '@/types';
import { displayFactLabel, displayFactValue, factLabels, safeStopCopy } from '@/lib/userCopy';

interface WorkflowResultCardProps {
  onOpenCase?: () => void;
  onContinueCase?: (facts: Record<string, string>, statuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>, taskType: CaseState['task_type']) => Promise<void>;
  onOpenSources?: () => void;
  onResearch?: () => void;
  workflow?: WorkflowMetadata;
}

export function WorkflowResultCard({ onOpenCase, onContinueCase, onOpenSources, onResearch, workflow }: WorkflowResultCardProps) {
  if (!workflow) return null;
  const rawStopReason = workflow.safe_stop_reason || workflow.citation_error || workflow.termination_reason || '';
  const stopKey = ({
    insufficient_evidence: 'insufficient_evidence',
    explicit_no_evidence_signal: 'missing_provision',
    explicit_article_not_found: 'missing_provision',
    outside_registered_corpus: 'out_of_scope',
    citation_verification_failed: 'failed_citation_verification',
    unavailable_dependency: 'unavailable_dependencies',
    dependency_unavailable: 'unavailable_dependencies',
    stale_corpus: 'stale_corpus',
    invalid_fact: 'invalid_or_unresolved_fact',
    unresolved_fact: 'invalid_or_unresolved_fact',
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
  const meaningfulAssumptions = (workflow.assumptions || []).filter((assumption) => assumption.trim());
  const hasAssumptions = Boolean(meaningfulAssumptions.length);
  const stop = safeStopCopy[stopKey] || {
    title: 'Chưa thể kết luận',
    message: 'Trợ lý đã dừng để tránh đưa ra kết luận không được nguồn hiện có hỗ trợ.',
  };
  const stopGuidance = stopKey === 'out_of_scope'
    ? 'Bạn có thể thử một câu hỏi về pháp luật EPR.'
    : stopKey === 'missing_provision'
      ? 'Nếu bạn có tên văn bản hoặc số điều khoản khác, hãy nêu thêm để trợ lý kiểm tra chính xác hơn.'
      : stopKey === 'unavailable_dependencies'
        ? 'Bạn có thể thử lại sau ít phút.'
        : 'Bạn có thể bổ sung thông tin hoặc thử lại.';

  const hasTrace = import.meta.env.VITE_ENABLE_TRACE_DEBUG === 'true' && Boolean(workflow.trace_id);
  if (!safeStop && !hasAssessment && !hasChecklist && !hasMissingFacts && !hasAssumptions && !hasTrace) return null;

  const taskType = workflow.case_state?.task_type || (workflow.task_type === 'build_compliance_checklist' ? 'build_compliance_checklist' : 'assess_epr_obligation');
  const factsUsed = Object.entries(workflow.case_state?.facts || {}).filter(([, value]) => {
    const raw = typeof value === 'string' ? value : (value as { value?: string })?.value;
    return Boolean(raw);
  });
  const caseFields = workflow.case_state?.fields || [];

  return (
    <section className="mt-5 space-y-3" aria-label="Kết quả xử lý">
      {hasMissingFacts && (
        onContinueCase ? (
          <GuidedCaseCard
            initialCaseState={workflow.case_state}
            onOpenFullEditor={onOpenCase}
            onSubmit={onContinueCase}
            taskType={taskType}
          />
        ) : (
          <div className="rounded-lg border border-[#cad5ec] bg-[#f3f6fc] p-4 text-sm text-[#29354b]">
            <p className="font-semibold text-[#005c55]">Cần thêm thông tin để tiếp tục</p>
            <p className="mt-2 leading-6">Còn thiếu: {workflow.missing_facts?.map((fact) => factLabels[fact] || fact).join(', ')}.</p>
          </div>
        )
      )}

      {safeStop && (
        <div className="rounded-lg border border-[#ead6b8] bg-[#fff8ea] p-4 text-sm text-[#714b18]">
          <div className="flex items-start gap-3">
            <Icon className="mt-0.5 shrink-0" name="alert" size={19} />
            <div>
              <p className="font-semibold">{stop.title}</p>
              <p className="mt-1 leading-6">{stop.message} {stopGuidance}</p>
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
              {factsUsed.length > 0 && <div className="mt-3"><p className="font-semibold">Thông tin đã sử dụng</p><ul className="mt-1 list-disc space-y-1 pl-5 text-sm">{factsUsed.map(([key, value]) => { const rawValue = typeof value === 'string' ? value : (value as { value?: string })?.value || ''; return <li key={key}>{displayFactLabel(key, caseFields)}: {displayFactValue(key, rawValue, caseFields)}</li>; })}</ul></div>}
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
            Danh sách việc cần làm
          </div>
          <ol className="mt-3 space-y-2.5">
            {workflow.checklist?.map((item, index) => (
              <li className="flex items-start gap-2.5 leading-6" key={index}>
                <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-[#80d5cb] text-[10px] font-semibold text-[#006a63]">
                  {index + 1}
                </span>
                <span><span className="font-medium">{String(item.item || 'Hạng mục cần thực hiện')}</span>{typeof item.action === 'string' && item.action && <span className="block text-xs text-[#667085]">{item.action}</span>}{Array.isArray(item.evidence_indices) && item.evidence_indices.length > 0 && (onOpenSources ? <button className="block text-left text-xs text-[#006a63] underline" onClick={onOpenSources} type="button">Xem căn cứ ({(item.evidence_indices as unknown[]).map((value) => String(value)).join(', ')})</button> : <span className="block text-xs text-[#006a63]">Căn cứ ({(item.evidence_indices as unknown[]).map((value) => String(value)).join(', ')})</span>)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {hasAssumptions && (
        <details className="rounded-lg border border-[#d9e1df] bg-[#f7faf8] px-4 py-3 text-sm text-[#53615e]">
          <summary className="cursor-pointer font-semibold text-[#3e4947]">Giả định đang sử dụng</summary>
          <ul className="mt-2 list-disc space-y-1.5 pl-5 leading-6">
            {meaningfulAssumptions.map((assumption, index) => <li key={index}>{assumption}</li>)}
          </ul>
        </details>
      )}
      <p className="text-[11px] text-[#667085]">Thông tin được cập nhật đến: {workflow.corpus_as_of_date || 'chưa xác nhận ngày cập nhật'}</p>
      <TraceDrawer traceId={workflow.trace_id} />
    </section>
  );
}
