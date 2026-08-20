import { useEffect, useState } from 'react';
import { Drawer } from '@/components/UI/Drawer';

interface TraceSpan {
  span_id: string;
  name: string;
  status: string;
  duration_ms?: number;
  error_message?: string;
  attributes?: Record<string, unknown>;
}

interface RetrievalCandidate {
  document_id?: string;
  legal_anchor?: string;
  dense_score?: number;
  bm25_score?: number;
  rrf_score?: number;
  rerank_score?: number;
  selected?: boolean;
  rejection_reason?: string;
}

interface Trace {
  trace_id: string;
  conversation_id: string;
  user_id: string;
  query: string;
  total_duration_ms?: number;
  spans: TraceSpan[];
}

interface TraceResponse {
  status: string;
  waterfall?: Trace;
  message?: string;
}

const enabled = import.meta.env.VITE_ENABLE_TRACE_DEBUG === 'true';

export function TraceDrawer({ traceId }: { traceId?: string }) {
  const [open, setOpen] = useState(false);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open || !traceId || trace) return;
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
    void fetch(`${baseUrl}/api/v1/traces/${encodeURIComponent(traceId)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 404 ? 'Trace debug chưa được bật.' : 'Không tải được trace.');
        const payload = (await response.json()) as TraceResponse;
        if (!payload.waterfall) throw new Error(payload.message || 'Không tải được trace.');
        return payload.waterfall;
      })
      .then(setTrace)
      .catch((reason: Error) => setError(reason.message));
  }, [open, trace, traceId]);

  if (!enabled || !traceId) return null;
  const copy = () => void navigator.clipboard?.writeText(traceId);
  const candidatesFor = (span: TraceSpan): RetrievalCandidate[] => {
    const candidates = span.attributes?.candidates;
    return Array.isArray(candidates) ? candidates as RetrievalCandidate[] : [];
  };
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <button className="rounded-md border border-[#d9e1df] bg-white px-3 py-1.5 text-xs font-semibold text-[#005c55] hover:bg-[#f1f4f3]" onClick={() => setOpen(true)} type="button">
        Chi tiết xử lý
      </button>
      <button className="rounded-md px-2 py-1.5 text-xs text-[#667085] hover:bg-[#f1f4f3]" onClick={copy} type="button">Sao chép mã trace</button>
      <Drawer description={`Mã trace: ${traceId}`} isOpen={open} onClose={() => setOpen(false)} title="Chi tiết xử lý">
        {error && <p className="text-sm text-[#ba1a1a]">{error}</p>}
        {!error && !trace && <p className="text-sm text-[#667085]">Đang tải trace…</p>}
        {trace && <div className="space-y-4 text-sm text-[#3e4947]">
          <p><strong>Truy vấn:</strong> {trace.query || '—'}</p>
          <p><strong>Thời lượng:</strong> {Math.round(trace.total_duration_ms || 0)} ms · <strong>Số span:</strong> {trace.spans.length}</p>
          <ol className="space-y-3">
            {trace.spans.map((span, index) => {
              const candidates = candidatesFor(span);
              return <li className="rounded-md border border-[#d9e1df] p-3" key={span.span_id}>
                <p className="font-semibold">{index + 1}. {span.name}</p>
                <p className="mt-1 text-xs text-[#667085]">{span.status}{span.duration_ms != null ? ` · ${Math.round(span.duration_ms)} ms` : ''}{span.error_message ? ` · ${span.error_message}` : ''}</p>
                {candidates.length > 0 && (
                  <div className="mt-3 overflow-x-auto">
                    <p className="mb-1 text-xs font-semibold text-[#3e4947]">Ứng viên truy xuất</p>
                    <table className="min-w-full text-left text-[11px] text-[#53615e]">
                      <thead className="border-b border-[#d9e1df] text-[#667085]">
                        <tr><th className="pr-2 pb-1">Điều</th><th className="pr-2 pb-1">Dense</th><th className="pr-2 pb-1">BM25</th><th className="pr-2 pb-1">RRF</th><th className="pb-1">Quyết định</th></tr>
                      </thead>
                      <tbody>
                        {candidates.map((candidate, index) => <tr className="border-b border-[#eef2f1]" key={`${candidate.document_id || index}`}>
                          <td className="max-w-28 truncate py-1 pr-2">{candidate.legal_anchor || candidate.document_id || '—'}</td>
                          <td className="py-1 pr-2">{candidate.dense_score?.toFixed(3) ?? '—'}</td>
                          <td className="py-1 pr-2">{candidate.bm25_score?.toFixed(3) ?? '—'}</td>
                          <td className="py-1 pr-2">{candidate.rrf_score?.toFixed(3) ?? '—'}</td>
                          <td className="py-1">{candidate.selected ? 'Đã chọn' : candidate.rejection_reason || 'Không chọn'}</td>
                        </tr>)}
                      </tbody>
                    </table>
                  </div>
                )}
              </li>;
            })}
          </ol>
        </div>}
      </Drawer>
    </div>
  );
}
