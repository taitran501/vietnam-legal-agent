import { cn } from '@/lib/cn';

interface HeaderProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  isHealthy: boolean;
}

/**
 * Modern header with status indicators
 */
export function Header({ sidebarOpen, onToggleSidebar, isHealthy }: HeaderProps) {
  return (
    <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white/80 dark:bg-gray-900/80 backdrop-blur-xl sticky top-0 z-10">
      <div className="flex items-center gap-3">
        {/* Sidebar toggle */}
        <button
          onClick={onToggleSidebar}
          className={cn(
            'p-2 rounded-lg transition-all duration-200 hover:bg-gray-100 dark:hover:bg-gray-800',
            'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
          )}
          aria-label={sidebarOpen ? 'Đóng sidebar' : 'Mở sidebar'}
        >
          <svg
            className="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            {sidebarOpen ? (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
              />
            ) : (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 5l7 7-7 7M5 5l7 7-7 7"
              />
            )}
          </svg>
        </button>

        {/* Logo and title */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center text-white text-lg shadow-lg shadow-green-500/20">
            ⚖️
          </div>
          <div>
            <h1 className="text-base font-semibold text-gray-900 dark:text-white leading-tight">
              Trợ lý EPR
            </h1>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Nghị định 08/2022/NĐ-CP
            </p>
          </div>
        </div>
      </div>

      {/* Status indicators */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-800">
          <div
            className={cn(
              'w-2 h-2 rounded-full',
              isHealthy ? 'bg-green-500 animate-pulse' : 'bg-red-500'
            )}
          />
          <span className="text-xs text-gray-600 dark:text-gray-400 font-medium">
            {isHealthy ? 'Sẵn sàng' : 'Ngoại tuyến'}
          </span>
        </div>
      </div>
    </header>
  );
}
