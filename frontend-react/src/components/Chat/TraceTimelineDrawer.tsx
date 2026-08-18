import { useState, useEffect } from 'react';
import { Icon } from '@/components/UI/Icon';

export interface SpanData {
  span_id: string;
  parent_span_id?: string | null;
  name: string;
  duration_ms: number;
  status: string;
  error_message?: string | null;
  input_tokens: number;
  output_tokens: number;
  model?: string;
  cost_usd?: number;
  attributes?: Record<string, unknown>;
}

export interface TraceSummaryData {
  trace_id: string;
  conversation_id: string;
  query: string;
  start_time: string;
  total_duration_ms: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  breakdown?: {
    retrieval_ms: number;
    llm_reasoning_ms: number;
  };
  spans_count: number;
  spans?: SpanData[];
}

interface TraceTimelineDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  traceId?: string;
  initialSummary?: TraceSummaryData | null;
}

export function TraceTimelineDrawer({
  isOpen,
  onClose,
  traceId,
  initialSummary,
}: TraceTimelineDrawerProps) {
  const [traceData, setTraceData] = useState<TraceSummaryData | null>(initialSummary || null);
  const [loading, setLoading] = useState(false);
  const [selectedSpan, setSelectedSpan] = useState<SpanData | null>(null);

  useEffect(() => {
    if (!isOpen || !traceId) return;

    const fetchTrace = async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/v1/traces/${traceId}`);
        if (res.ok) {
          const data = await res.json();
          if (data.waterfall) {
            setTraceData(data.waterfall);
            if (data.waterfall.spans && data.waterfall.spans.length > 0) {
              setSelectedSpan(data.waterfall.spans[0]);
            }
          }
        }
      } catch {
        // Fallback to initialSummary if fetch fails
        if (initialSummary) setTraceData(initialSummary);
      } finally {
        setLoading(false);
      }
    };

    fetchTrace();
  }, [isOpen, traceId, initialSummary]);

  if (!isOpen) return null;

  const totalMs = traceData?.total_duration_ms || 1;
  const spans = traceData?.spans || [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-sm animate-[fadeIn_150ms_ease-out]">
      <div
        className="flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl animate-[slideLeft_200ms_ease-out]"
        role="dialog"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-teal-50 text-teal-800 ring-1 ring-teal-600/20">
              <Icon name="history" size={16} />
            </span>
            <div>
              <h3 className="text-sm font-bold text-slate-900">Trace Telemetry & Performance Waterfall</h3>
              <p className="text-xs text-slate-500 font-mono">ID: {traceId || 'N/A'}</p>
            </div>
          </div>
          <button
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            onClick={onClose}
            type="button"
          >
            <Icon name="close" size={18} />
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex h-48 items-center justify-center">
              <span className="h-6 w-6 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
            </div>
          ) : (
            <div className="space-y-6">
              {/* Metrics Summary Grid */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                  <span className="text-[11px] font-semibold text-slate-500 uppercase">Tổng thời gian</span>
                  <p className="mt-1 text-lg font-bold text-slate-900">
                    {traceData?.total_duration_ms ? `${(traceData.total_duration_ms / 1000).toFixed(2)}s` : '--'}
                  </p>
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                  <span className="text-[11px] font-semibold text-slate-500 uppercase">Tổng Tokens</span>
                  <p className="mt-1 text-lg font-bold text-slate-900">
                    {traceData?.total_tokens?.toLocaleString() || '--'}
                  </p>
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                  <span className="text-[11px] font-semibold text-slate-500 uppercase">Ước tính Chi phí</span>
                  <p className="mt-1 text-lg font-bold text-teal-900">
                    ${traceData?.estimated_cost_usd?.toFixed(5) || '0.00000'}
                  </p>
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                  <span className="text-[11px] font-semibold text-slate-500 uppercase">Số Spans</span>
                  <p className="mt-1 text-lg font-bold text-slate-900">
                    {spans.length || traceData?.spans_count || '--'}
                  </p>
                </div>
              </div>

              {/* Waterfall Timeline */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">
                  Biểu đồ Waterfall Timeline từng chặng
                </h4>

                <div className="mt-3 space-y-2 rounded-xl border border-slate-200 bg-slate-50/50 p-4">
                  {spans.length > 0 ? (
                    spans.map((span) => {
                      const widthPct = Math.max(5, Math.min(100, (span.duration_ms / totalMs) * 100));
                      const isSelected = selectedSpan?.span_id === span.span_id;

                      return (
                        <div
                          className={`cursor-pointer rounded-lg p-2 transition-all ${
                            isSelected ? 'bg-teal-50 ring-1 ring-teal-600/30' : 'hover:bg-white'
                          }`}
                          key={span.span_id}
                          onClick={() => setSelectedSpan(span)}
                        >
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-mono font-semibold text-slate-800">{span.name}</span>
                            <span className="font-mono text-slate-500">{span.duration_ms} ms</span>
                          </div>

                          {/* Progress bar */}
                          <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-200">
                            <div
                              className={`h-full rounded-full ${
                                span.status === 'ok' ? 'bg-teal-600' : 'bg-amber-500'
                              }`}
                              style={{ width: `${widthPct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <p className="text-xs text-slate-500">Không có dữ liệu spans chi tiết cho lượt này.</p>
                  )}
                </div>
              </div>

              {/* Span Inspector Box */}
              {selectedSpan && (
                <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                    <span className="font-mono font-bold text-xs text-slate-900">
                      Chi tiết Span: {selectedSpan.name}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                        selectedSpan.status === 'ok' ? 'bg-emerald-50 text-emerald-800' : 'bg-rose-50 text-rose-800'
                      }`}
                    >
                      {selectedSpan.status.toUpperCase()}
                    </span>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
                    <div>
                      <span className="font-medium text-slate-500">Thời lượng:</span>{' '}
                      <span className="font-mono text-slate-800">{selectedSpan.duration_ms} ms</span>
                    </div>
                    <div>
                      <span className="font-medium text-slate-500">Model:</span>{' '}
                      <span className="font-mono text-slate-800">{selectedSpan.model || 'N/A'}</span>
                    </div>
                    <div>
                      <span className="font-medium text-slate-500">Input Tokens:</span>{' '}
                      <span className="font-mono text-slate-800">{selectedSpan.input_tokens}</span>
                    </div>
                    <div>
                      <span className="font-medium text-slate-500">Output Tokens:</span>{' '}
                      <span className="font-mono text-slate-800">{selectedSpan.output_tokens}</span>
                    </div>
                  </div>

                  {selectedSpan.attributes && Object.keys(selectedSpan.attributes).length > 0 && (
                    <div className="mt-3">
                      <span className="text-[11px] font-semibold text-slate-500 uppercase">Thuộc tính (Attributes):</span>
                      <pre className="mt-1 max-h-32 overflow-x-auto rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-700">
                        {JSON.stringify(selectedSpan.attributes, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
