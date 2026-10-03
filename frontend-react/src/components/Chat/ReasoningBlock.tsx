import React, { useState, useEffect, useMemo } from 'react';
import type { WorkflowStep } from '@/types';
import { Icon, type IconName } from '@/components/UI/Icon';

export interface ReasoningBlockProps {
  isStreaming?: boolean;
  statusMessage?: string;
  steps?: WorkflowStep[];
  defaultExpanded?: boolean;
}

const STEP_DEFINITIONS: Record<
  string,
  { label: string; icon: IconName; defaultBadge?: string }
> = {
  validate_input: {
    label: 'Kiểm tra tính hợp lệ & phạm vi câu hỏi',
    icon: 'shield',
    defaultBadge: 'Chuẩn hóa đầu vào',
  },
  load_context: {
    label: 'Nạp lịch sử & ngữ cảnh vụ việc',
    icon: 'history',
    defaultBadge: 'Phiên hội thoại',
  },
  understand_task: {
    label: 'Hiểu yêu cầu & phân tích quan hệ pháp lý',
    icon: 'brain',
    defaultBadge: 'Ý định & quan hệ pháp luật',
  },
  classify_route: {
    label: 'Xác định quan hệ pháp luật & nhánh luật áp dụng',
    icon: 'scale',
    defaultBadge: 'Định tuyến luật',
  },
  lookup_answer_cache: {
    label: 'Kiểm tra kho tình huống đã thẩm định',
    icon: 'sparkles',
    defaultBadge: 'Kho giải đáp đã kiểm chứng',
  },
  check_cache: {
    label: 'Kiểm tra bộ nhớ đệm câu trả lời',
    icon: 'sparkles',
    defaultBadge: 'Cache tiền thẩm định',
  },
  search_legal_provisions: {
    label: 'Truy xuất kho văn bản & điều khoản pháp luật',
    icon: 'search',
    defaultBadge: 'Kho văn bản đã cấu hình',
  },
  retrieve_legal: {
    label: 'Truy xuất căn cứ pháp luật chuyên ngành',
    icon: 'search',
    defaultBadge: 'Ensemble BM25 & Vector',
  },
  evaluate_legal_case: {
    label: 'Áp dụng quy tắc pháp lý & đối chiếu điều kiện',
    icon: 'scale',
    defaultBadge: 'Đánh giá điều kiện luật định',
  },
  evaluate_evidence: {
    label: 'Đánh giá mức độ đầy đủ của căn cứ pháp lý',
    icon: 'fileCheck',
    defaultBadge: 'Thẩm định chứng cứ',
  },
  calculate_statutory_amounts: {
    label: 'Tính toán trợ cấp, tiền lương & bồi thường luật định',
    icon: 'calculator',
    defaultBadge: 'Công thức luật định',
  },
  search_web_official: {
    label: 'Tra cứu bổ sung từ Cổng TTĐT Chính phủ / Bộ / Ngành',
    icon: 'globe',
    defaultBadge: 'Cổng TTĐT chính thức',
  },
  retrieve_web: {
    label: 'Tra cứu nguồn chính thức trên web',
    icon: 'globe',
    defaultBadge: 'Web chính phủ',
  },
  compose_answer: {
    label: 'Soạn thảo nội dung tư vấn pháp lý có căn cứ',
    icon: 'book',
    defaultBadge: 'Tư vấn pháp lý',
  },
  verify_citations: {
    label: 'Thẩm định phản biện & rà soát hiệu lực văn bản',
    icon: 'fileCheck',
    defaultBadge: 'Rà soát hiệu lực VBPL',
  },
  critic_review: {
    label: 'Hội đồng phản biện cao cấp duyệt câu trả lời',
    icon: 'fileCheck',
    defaultBadge: 'Kiểm duyệt chất lượng',
  },
  finish: {
    label: 'Hoàn tất quy trình tra cứu & tư vấn',
    icon: 'check',
    defaultBadge: 'Hoàn tất',
  },
};

/**
 * Deer-Flow style Tool Call Details preview with copy functionality
 */
function ToolCallDetailsView({
  args,
  details,
}: {
  args?: Record<string, unknown>;
  details?: unknown;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const payload = args || (typeof details === 'object' ? details : { details });
  if (!payload || Object.keys(payload).length === 0) return null;

  const jsonString = JSON.stringify(payload, null, 2);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        className="text-[11px] font-medium text-slate-500 hover:text-slate-700 underline underline-offset-2"
      >
        {open ? 'Ẩn chi tiết tham số' : 'Xem chi tiết tham số'}
      </button>

      {open && (
        <div className="mt-1.5 rounded-lg border border-slate-200 bg-slate-100/70 p-2.5 text-left">
          <div className="flex items-center justify-between pb-1 mb-1 border-b border-slate-200 text-[10px] text-slate-500 font-semibold uppercase tracking-wider">
            <span>Tham số đầu vào / Dữ liệu trả về</span>
            <button
              type="button"
              onClick={handleCopy}
              className="text-[#006a63] hover:underline"
            >
              {copied ? 'Đã sao chép ✓' : 'Sao chép'}
            </button>
          </div>
          <pre className="max-h-40 overflow-auto font-mono text-[11px] leading-relaxed text-slate-700 break-all whitespace-pre-wrap">
            {jsonString}
          </pre>
        </div>
      )}
    </div>
  );
}

/**
 * Deer-Flow inspired Chain of Thought & Reasoning Timeline
 */
export function ReasoningBlock({
  isStreaming = false,
  statusMessage,
  steps = [],
  defaultExpanded,
}: ReasoningBlockProps) {
  const [isOpen, setIsOpen] = useState<boolean>(() => defaultExpanded ?? isStreaming);
  const [userToggled, setUserToggled] = useState<boolean>(false);
  const [startTime, setStartTime] = useState<number | null>(() => (isStreaming ? Date.now() : null));
  const [elapsed, setElapsed] = useState<number>(0);
  const [finalDuration, setFinalDuration] = useState<number | null>(null);

  // Live timer tracking during streaming
  useEffect(() => {
    if (isStreaming) {
      if (!startTime) setStartTime(Date.now());
      const timer = setInterval(() => {
        if (startTime) {
          setElapsed(Math.max(1, Math.floor((Date.now() - startTime) / 1000)));
        }
      }, 1000);
      return () => clearInterval(timer);
    } else if (startTime !== null) {
      const dur = Math.max(1, Math.floor((Date.now() - startTime) / 1000));
      setFinalDuration(dur);
      setStartTime(null);
    }
  }, [isStreaming, startTime]);

  // When streaming starts, auto-open if user hasn't explicitly toggled
  useEffect(() => {
    if (isStreaming && !userToggled) {
      setIsOpen(true);
    }
  }, [isStreaming, userToggled]);

  // Auto-close 1.2s after streaming completes if user didn't manually toggle
  useEffect(() => {
    if (!isStreaming && !defaultExpanded && !userToggled && isOpen) {
      const timer = setTimeout(() => {
        setIsOpen(false);
      }, 1200);
      return () => clearTimeout(timer);
    }
  }, [isStreaming, defaultExpanded, userToggled, isOpen]);

  // Filter valid steps
  const displaySteps = useMemo(() => {
    return steps.filter((step) => Boolean(step.action));
  }, [steps]);

  // If currently streaming and there is a status message but no steps yet, synthesize an active initial step
  const activeStepList = useMemo(() => {
    if (displaySteps.length > 0) return displaySteps;
    if (isStreaming) {
      return [
        {
          step: 1,
          action: 'search_legal_provisions',
          label: statusMessage || 'Đang tra cứu kho văn bản quy phạm pháp luật…',
          status: 'running',
        } as WorkflowStep,
      ];
    }
    return [];
  }, [displaySteps, isStreaming, statusMessage]);

  const stepCount = activeStepList.length;

  return (
    <div
      data-testid="reasoning-block"
      className="my-2.5 w-full rounded-xl border border-slate-200/90 bg-slate-50/60 text-xs text-slate-600 transition-all shadow-2xs overflow-hidden"
    >
      {/* Header bar / Toggle */}
      <button
        type="button"
        onClick={() => {
          setUserToggled(true);
          setIsOpen(!isOpen);
        }}
        aria-expanded={isOpen}
        className="flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left font-medium text-slate-700 transition-colors hover:bg-slate-100/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#006a63]"
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg ${
              isStreaming
                ? 'bg-[#006a63]/15 text-[#006a63] motion-safe:animate-pulse'
                : 'bg-emerald-50 text-emerald-700 border border-emerald-200/60'
            }`}
          >
            <Icon name={isStreaming ? 'brain' : 'check'} size={14} />
          </span>

          <div className="min-w-0 flex items-center gap-2">
            <span className="truncate font-semibold text-slate-800 text-[13px]">
              {isStreaming
                ? 'Tiến trình tra cứu & suy luận pháp lý…'
                : `Đã đối chiếu & suy luận qua ${stepCount > 0 ? `${stepCount} bước` : 'các bước pháp lý'}`}
            </span>

            {/* Live Timer or Final Duration Pill */}
            {isStreaming && (
              <span className="inline-flex items-center gap-1 rounded-full bg-[#006a63]/10 px-2 py-0.5 text-[10px] font-semibold text-[#006a63]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#006a63] animate-ping" />
                {elapsed}s
              </span>
            )}
            {!isStreaming && finalDuration !== null && finalDuration > 0 && (
              <span className="rounded-full bg-slate-200/70 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                {finalDuration}s
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1 text-[11px] font-medium text-slate-500">
          <span>{isOpen ? 'Thu gọn' : 'Chi tiết'}</span>
          <Icon
            className={`transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
            name="chevronDown"
            size={13}
          />
        </div>
      </button>

      {/* Expanded Chain of Thought Timeline */}
      {isOpen && (
        <div className="border-t border-slate-200/70 bg-white/70 px-4 py-3">
          <div className="relative pl-6 space-y-4">
            {/* Continuous vertical timeline bar */}
            <div className="absolute left-[11px] top-2 bottom-2 w-0.5 bg-slate-200" />

            {activeStepList.map((step, idx) => {
              const def = STEP_DEFINITIONS[step.action] || {
                label: step.label || step.action,
                icon: 'book',
                defaultBadge: undefined,
              };

              const isLast = idx === activeStepList.length - 1;
              const isRunning = isStreaming && isLast && step.status !== 'completed';
              const label = def.label || step.label || step.action;
              const iconName: IconName = def.icon;

              // Extract any search queries or legal anchors for pills
              const args = step.details && typeof step.details === 'object'
                ? (step.details as Record<string, unknown>)
                : undefined;
              const searchQuery = typeof args?.query === 'string' ? args.query : undefined;

              return (
                <div key={`${step.step}-${step.action}-${idx}`} className="relative flex items-start gap-3">
                  {/* Timeline Node Icon */}
                  <span
                    className={`absolute -left-6 top-0.5 flex h-5 w-5 items-center justify-center rounded-full ring-4 ring-white ${
                      isRunning
                        ? 'bg-[#006a63] text-white shadow-sm'
                        : 'bg-emerald-100 text-emerald-800'
                    }`}
                  >
                    {isRunning ? (
                      <span className="h-2 w-2 rounded-full bg-white animate-ping" />
                    ) : (
                      <Icon name={iconName} size={11} />
                    )}
                  </span>

                  {/* Step Body */}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`text-[12px] leading-tight font-medium ${
                          isRunning ? 'font-bold text-[#006a63]' : 'text-slate-800'
                        }`}
                      >
                        {label}
                      </span>

                      {/* Latency badge */}
                      {typeof step.latency_ms === 'number' && step.latency_ms > 0 && (
                        <span className="text-[10px] text-slate-400 font-mono">
                          {step.latency_ms > 1000
                            ? `${(step.latency_ms / 1000).toFixed(1)}s`
                            : `${Math.round(step.latency_ms)}ms`}
                        </span>
                      )}
                    </div>

                    {/* Deer-Flow Search Badges & Pills */}
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      {def.defaultBadge && (
                        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600 border border-slate-200/80">
                          {def.defaultBadge}
                        </span>
                      )}

                      {searchQuery && (
                        <span className="inline-flex items-center gap-1 rounded bg-[#006a63]/10 px-2 py-0.5 text-[10px] font-medium text-[#006a63] border border-[#006a63]/20">
                          <Icon name="search" size={10} />
                          &ldquo;{searchQuery}&rdquo;
                        </span>
                      )}

                      {isRunning && (
                        <span className="inline-flex items-center gap-1 text-[11px] text-[#006a63] italic">
                          <span className="h-1.5 w-1.5 rounded-full bg-[#006a63] animate-pulse" />
                          Đang thực thi…
                        </span>
                      )}
                    </div>

                    {/* Tool Call Parameters / Observation Details */}
                    {args && Object.keys(args).length > 0 && (
                      <ToolCallDetailsView args={args} />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
