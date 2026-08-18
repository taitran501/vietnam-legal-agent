import { useState } from 'react';
import { Icon } from '@/components/UI/Icon';

export interface ClauseReviewItem {
  clause_id: string;
  clause_title: string;
  original_text: string;
  risk_level: 'high' | 'medium' | 'low' | 'safe';
  statutory_conflict?: string | null;
  issue_description: string;
  suggested_redline: string;
}

export interface ContractRedlineReportData {
  document_title: string;
  contract_type: string;
  overall_risk: 'high' | 'medium' | 'low';
  total_clauses: number;
  high_risk_count: number;
  medium_risk_count: number;
  safe_clause_count: number;
  executive_summary: string;
  clause_reviews: ClauseReviewItem[];
  negotiation_strategy?: string[];
}

interface ContractRedlineCardProps {
  report: ContractRedlineReportData;
}

export function ContractRedlineCard({ report }: ContractRedlineCardProps) {
  const [filter, setFilter] = useState<'all' | 'high' | 'medium' | 'safe'>('all');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const filteredClauses = report.clause_reviews.filter((item) => {
    if (filter === 'all') return true;
    return item.risk_level === filter;
  });

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    window.setTimeout(() => setCopiedId(null), 2000);
  };

  const riskBadgeConfig = {
    high: {
      label: 'Rủi ro Cao (Trái luật/Vô hiệu)',
      bg: 'bg-rose-50 border-rose-200 text-rose-800',
      dot: 'bg-rose-500',
    },
    medium: {
      label: 'Rủi ro Trung bình (Bất lợi/Mập mờ)',
      bg: 'bg-amber-50 border-amber-200 text-amber-800',
      dot: 'bg-amber-500',
    },
    low: {
      label: 'Lưu ý nhỏ',
      bg: 'bg-blue-50 border-blue-200 text-blue-800',
      dot: 'bg-blue-500',
    },
    safe: {
      label: 'An toàn / Chuẩn luật',
      bg: 'bg-emerald-50 border-emerald-200 text-emerald-800',
      dot: 'bg-emerald-500',
    },
  };

  return (
    <div className="my-4 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      {/* Header Banner */}
      <div className="border-b border-slate-100 bg-slate-50/80 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal-100 text-teal-800 ring-1 ring-teal-600/20">
              <Icon name="fileCheck" size={18} />
            </span>
            <div>
              <h3 className="text-base font-bold text-slate-900">
                Bảng Phân tích & Rà soát Hợp đồng (Contract Redline Matrix)
              </h3>
              <p className="text-xs text-slate-500">{report.document_title} · {report.contract_type}</p>
            </div>
          </div>

          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold ${
              report.overall_risk === 'high'
                ? 'border-rose-300 bg-rose-50 text-rose-800'
                : report.overall_risk === 'medium'
                ? 'border-amber-300 bg-amber-50 text-amber-800'
                : 'border-emerald-300 bg-emerald-50 text-emerald-800'
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${
                report.overall_risk === 'high'
                  ? 'bg-rose-500'
                  : report.overall_risk === 'medium'
                  ? 'bg-amber-500'
                  : 'bg-emerald-500'
              }`}
            />
            {report.overall_risk === 'high'
              ? 'Rủi ro Tổng thể: CAO'
              : report.overall_risk === 'medium'
              ? 'Rủi ro Tổng thể: TRUNG BÌNH'
              : 'Rủi ro Tổng thể: AN TOÀN'}
          </span>
        </div>

        {/* Executive Summary */}
        <p className="mt-3 text-xs leading-relaxed text-slate-600 sm:text-sm">
          {report.executive_summary}
        </p>

        {/* Stats counter bar */}
        <div className="mt-4 flex flex-wrap gap-2 text-xs">
          <button
            className={`rounded-lg border px-3 py-1.5 font-medium transition-all ${
              filter === 'all'
                ? 'border-slate-800 bg-slate-900 text-white shadow-sm'
                : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
            }`}
            onClick={() => setFilter('all')}
            type="button"
          >
            Tất cả ({report.total_clauses})
          </button>
          {report.high_risk_count > 0 && (
            <button
              className={`rounded-lg border px-3 py-1.5 font-medium transition-all ${
                filter === 'high'
                  ? 'border-rose-600 bg-rose-600 text-white shadow-sm'
                  : 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100'
              }`}
              onClick={() => setFilter('high')}
              type="button"
            >
              🔴 Rủi ro cao ({report.high_risk_count})
            </button>
          )}
          {report.medium_risk_count > 0 && (
            <button
              className={`rounded-lg border px-3 py-1.5 font-medium transition-all ${
                filter === 'medium'
                  ? 'border-amber-600 bg-amber-600 text-white shadow-sm'
                  : 'border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100'
              }`}
              onClick={() => setFilter('medium')}
              type="button"
            >
              🟡 Rủi ro trung bình ({report.medium_risk_count})
            </button>
          )}
          {report.safe_clause_count > 0 && (
            <button
              className={`rounded-lg border px-3 py-1.5 font-medium transition-all ${
                filter === 'safe'
                  ? 'border-emerald-600 bg-emerald-600 text-white shadow-sm'
                  : 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
              }`}
              onClick={() => setFilter('safe')}
              type="button"
            >
              🟢 An toàn ({report.safe_clause_count})
            </button>
          )}
        </div>
      </div>

      {/* Clause Items List */}
      <div className="divide-y divide-slate-100 p-4 sm:p-5">
        {filteredClauses.map((clause) => {
          const cfg = riskBadgeConfig[clause.risk_level] || riskBadgeConfig.safe;
          const isCopied = copiedId === clause.clause_id;

          return (
            <article className="py-4 first:pt-0 last:pb-0" key={clause.clause_id}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-slate-900 text-sm">{clause.clause_title}</span>
                  {clause.statutory_conflict && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-700 ring-1 ring-rose-600/20">
                      <Icon name="scale" size={11} />
                      Xung đột: {clause.statutory_conflict}
                    </span>
                  )}
                </div>

                <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${cfg.bg}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
                  {cfg.label}
                </span>
              </div>

              {/* Issue Description */}
              <p className="mt-2 text-xs leading-relaxed text-slate-700">
                <span className="font-semibold text-slate-900">Phân tích rủi ro:</span> {clause.issue_description}
              </p>

              {/* Redline comparison */}
              <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
                {/* Original */}
                <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs leading-relaxed text-slate-600">
                  <p className="mb-1 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                    [Điều khoản gốc hiện tại]
                  </p>
                  <p className="whitespace-pre-wrap">{clause.original_text}</p>
                </div>

                {/* Suggested Redline */}
                <div className="rounded-xl border border-teal-200 bg-teal-50/40 p-3 text-xs leading-relaxed text-slate-800">
                  <div className="mb-1 flex items-center justify-between">
                    <p className="text-[11px] font-bold uppercase tracking-wider text-teal-800">
                      [Đề xuất sửa đổi an toàn (Redline)]
                    </p>
                    <button
                      className="inline-flex items-center gap-1 rounded bg-white px-2 py-0.5 text-[10px] font-semibold text-teal-800 shadow-sm ring-1 ring-teal-600/20 hover:bg-teal-50"
                      onClick={() => handleCopy(clause.clause_id, clause.suggested_redline)}
                      type="button"
                    >
                      <Icon name={isCopied ? 'check' : 'copy'} size={11} />
                      {isCopied ? 'Đã chép' : 'Sao chép'}
                    </button>
                  </div>
                  <p className="whitespace-pre-wrap font-medium">{clause.suggested_redline}</p>
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {/* Negotiation Strategy footer */}
      {report.negotiation_strategy && report.negotiation_strategy.length > 0 && (
        <div className="border-t border-slate-100 bg-slate-50/60 p-4 text-xs text-slate-600">
          <p className="font-bold text-slate-800">Khuyến nghị chiến lược đàm phán:</p>
          <ul className="mt-1.5 list-inside list-disc space-y-1">
            {report.negotiation_strategy.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
