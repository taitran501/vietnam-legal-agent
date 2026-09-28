import { useState } from 'react';
import type { CaseState } from '@/types';
import { Icon } from '@/components/UI/Icon';
import { displayFactLabel, displayFactValue, taskCopy } from '@/lib/userCopy';
import { cn } from '@/lib/cn';

interface ActiveCaseProgressProps {
  caseState: CaseState;
  onOpenCase?: () => void;
  className?: string;
}

export function ActiveCaseProgress({ caseState, onOpenCase, className }: ActiveCaseProgressProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  const factsList = Object.entries(caseState.facts || {})
    .map(([key, rawValue]) => {
      const val = typeof rawValue === 'string' ? rawValue : rawValue?.value;
      return {
        key,
        label: displayFactLabel(key, caseState.fields),
        value: val ? displayFactValue(key, val) : '',
      };
    })
    .filter((f) => Boolean(f.value));

  const missingFactsList = (caseState.missing_facts || []).map((key) => ({
    key,
    label: displayFactLabel(key, caseState.fields),
  }));

  const copy = taskCopy[caseState.task_type] || {
    title: 'Hồ sơ vụ việc đang xử lý',
    action: 'Đánh giá vụ việc',
  };

  const isReady = caseState.status === 'ready' || (missingFactsList.length === 0 && factsList.length > 0);
  const totalCount = caseState.required_count ?? (caseState.fields ? caseState.fields.filter((f) => f.required).length : factsList.length + missingFactsList.length);
  const completedCount = caseState.completed_count ?? factsList.length;
  const progressPercent = totalCount > 0 ? Math.min(100, Math.round((completedCount / totalCount) * 100)) : 100;

  return (
    <aside
      aria-label="Tiến độ dữ kiện vụ việc"
      className={cn(
        'mx-auto w-full max-w-[820px] rounded-xl border transition-all duration-200',
        isReady
          ? 'border-emerald-200 bg-emerald-50/40 text-emerald-950 shadow-xs'
          : 'border-teal-200/90 bg-white text-slate-900 shadow-sm ring-1 ring-teal-600/10',
        className,
      )}
    >
      {/* Header bar */}
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={cn(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs',
              isReady
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-teal-50 text-teal-700 ring-1 ring-teal-600/20',
            )}
          >
            <Icon name={caseState.task_type === 'build_compliance_checklist' ? 'checklist' : 'scale'} size={15} />
          </span>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900">
                {copy.title}
              </h2>
              <span
                className={cn(
                  'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold',
                  isReady
                    ? 'bg-emerald-100 text-emerald-800'
                    : 'bg-amber-100 text-amber-900',
                )}
              >
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    isReady ? 'bg-emerald-600' : 'bg-amber-500 animate-pulse',
                  )}
                />
                {isReady ? 'Đã đủ dữ kiện' : `Đang thu thập (${missingFactsList.length} mục cần thêm)`}
              </span>
            </div>
          </div>
        </div>

        {/* Right action controls */}
        <div className="flex items-center gap-2 shrink-0">
          {onOpenCase && (
            <button
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-teal-800 hover:bg-teal-50 hover:text-teal-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600"
              onClick={onOpenCase}
              title="Mở bảng nhập liệu vụ việc đầy đủ"
              type="button"
            >
              <Icon name="case" size={13} />
              <span className="hidden sm:inline">Mở bảng chi tiết</span>
            </button>
          )}

          <button
            aria-expanded={isExpanded}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600"
            onClick={() => setIsExpanded((prev) => !prev)}
            type="button"
          >
            <span>{isExpanded ? 'Thu gọn' : 'Xem chi tiết'}</span>
            <Icon
              className={cn('transition-transform duration-200', isExpanded ? 'rotate-180' : 'rotate-0')}
              name="chevronDown"
              size={13}
            />
          </button>
        </div>
      </div>

      {/* Expanded progress details */}
      {isExpanded && (
        <div className="border-t border-slate-100 px-4 pb-4 pt-3 text-xs">
          {/* Progress bar */}
          <div className="mb-3">
            <div className="flex items-center justify-between text-[11px] font-medium text-slate-500">
              <span>Tiến độ dữ kiện thu thập</span>
              <span className="font-semibold text-teal-800">
                {completedCount}/{totalCount || completedCount} thông tin ({progressPercent}%)
              </span>
            </div>
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className={cn(
                  'h-full transition-all duration-300',
                  isReady ? 'bg-emerald-600' : 'bg-teal-600',
                )}
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          {/* Supplied facts */}
          {factsList.length > 0 && (
            <div className="mb-2.5">
              <p className="mb-1.5 font-semibold text-slate-700">Dữ kiện đã ghi nhận:</p>
              <div className="flex flex-wrap gap-1.5">
                {factsList.map((f) => (
                  <span
                    className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800 ring-1 ring-emerald-600/20"
                    key={f.key}
                  >
                    <Icon className="text-emerald-600 shrink-0" name="check" size={11} />
                    <span className="font-semibold">{f.label}:</span>
                    <span className="max-w-[240px] truncate">{f.value}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Missing facts */}
          {missingFactsList.length > 0 && (
            <div>
              <p className="mb-1.5 font-semibold text-amber-900">Dữ kiện đang chờ bổ sung:</p>
              <div className="flex flex-wrap gap-1.5">
                {missingFactsList.map((mf) => (
                  <span
                    className="inline-flex items-center gap-1.5 rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-600/20"
                    key={mf.key}
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                    <span>{mf.label}</span>
                  </span>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-slate-500">
                💡 Bạn có thể trả lời trực tiếp vào ô chat bên dưới để trợ lý cập nhật hồ sơ và tiếp tục đối chiếu quy định.
              </p>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
