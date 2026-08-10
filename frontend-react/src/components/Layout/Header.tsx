import { Icon } from '@/components/UI/Icon';

interface HeaderProps {
  hasActiveCase?: boolean;
  readiness: 'ready' | 'preparing' | 'missing' | 'offline';
  onOpenCase?: () => void;
  onOpenMobileNav: () => void;
}

export function Header({ hasActiveCase = false, readiness, onOpenCase, onOpenMobileNav }: HeaderProps) {
  const status = {
    ready: { label: 'Sẵn sàng', color: 'bg-[#1d8b66]', title: 'Dữ liệu pháp luật đã sẵn sàng' },
    preparing: { label: 'Đang chuẩn bị dữ liệu', color: 'bg-[#d98b22]', title: 'Đang chuẩn bị dữ liệu pháp luật' },
    missing: { label: 'Thiếu dữ liệu pháp luật', color: 'bg-[#ba1a1a]', title: 'Chưa có law index' },
    offline: { label: 'Ngoại tuyến', color: 'bg-[#ba1a1a]', title: 'Không thể kết nối tới máy chủ' },
  }[readiness];
  return (
    <header className="z-20 flex h-16 shrink-0 items-center justify-between border-b border-[#d9e1df] bg-[#fcfcfa]/95 px-3 backdrop-blur sm:px-5">
      <div className="flex min-w-0 items-center gap-2.5">
        <button
          aria-label="Mở lịch sử trò chuyện"
          className="rounded-md p-2 text-[#53615e] transition-colors hover:bg-[#e7eceb] hover:text-[#172033] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e] md:hidden"
          onClick={onOpenMobileNav}
          type="button"
        >
          <Icon name="menu" size={21} />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-sm font-semibold text-[#172033] sm:text-base">Trợ lý pháp lý</h1>
            <span className="rounded-full bg-[#e7eceb] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#006a63]">
              EPR
            </span>
          </div>
          <p className="hidden text-[11px] text-[#667085] sm:block">Tra cứu · Làm rõ · Chuẩn bị bước tiếp theo</p>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {hasActiveCase && (
          <button
            aria-label="Mở thông tin tình huống"
            className="inline-flex items-center gap-2 rounded-md px-2.5 py-2 text-xs font-semibold text-[#005c55] transition-colors hover:bg-[#e7eceb] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e] sm:text-sm"
            onClick={onOpenCase}
            type="button"
          >
            <Icon name="case" size={17} />
            <span className="hidden sm:inline">Thông tin tình huống</span>
          </button>
        )}
        <div
          className="inline-flex items-center gap-2 rounded-full border border-[#d9e1df] bg-white px-2.5 py-1.5"
          title={status.title}
        >
          <span className={`h-2 w-2 rounded-full ${status.color}`} />
          <span className="hidden text-[11px] font-medium text-[#667085] sm:inline">
            {status.label}
          </span>
        </div>
      </div>
    </header>
  );
}
