import { useEffect, useState } from 'react';
import { Drawer } from '@/components/UI/Drawer';

interface TraceEvent {
  sequence: number;
  node: string;
  status: string;
  reason_code?: string;
  tool_name?: string;
  duration_ms?: number;
  error_code?: string;
  payload?: Record<string, unknown>;
}

interface Trace {
  trace_id: string;
  action_sequence: string[];
  termination_reason?: string;
  duration_ms?: number;
  source?: string;
  events: TraceEvent[];
}

const enabled = import.meta.env.VITE_ENABLE_TRACE_DEBUG === 'true';

export function TraceDrawer({ traceId }: { traceId?: string }) {
  const [open, setOpen] = useState(false);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open || !traceId || trace) return;
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
    void fetch(`${baseUrl}/api/v1/debug/traces/${encodeURIComponent(traceId)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 404 ? 'Trace debug chưa được bật.' : 'Không tải được trace.');
        return response.json() as Promise<Trace>;
      })
      .then(setTrace)
      .catch((reason: Error) => setError(reason.message));
  }, [open, trace, traceId]);

  if (!enabled || !traceId) return null;
  const copy = () => void navigator.clipboard?.writeText(traceId);
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
          <p><strong>Kết thúc:</strong> {trace.termination_reason || '—'} · {Math.round(trace.duration_ms || 0)} ms</p>
          <ol className="space-y-3">
            {trace.events.map((event) => <li className="rounded-md border border-[#d9e1df] p-3" key={`${event.sequence}-${event.node}`}>
              <p className="font-semibold">{event.sequence}. {event.node}</p>
              <p className="mt-1 text-xs text-[#667085]">{event.reason_code || event.status}{event.tool_name ? ` · ${event.tool_name}` : ''}{event.duration_ms != null ? ` · ${Math.round(event.duration_ms)} ms` : ''}</p>
              {event.payload?.candidates ? <p className="mt-2 text-xs">Đã ghi candidate retrieval và quyết định evidence.</p> : null}
            </li>)}
          </ol>
        </div>}
      </Drawer>
    </div>
  );
}
