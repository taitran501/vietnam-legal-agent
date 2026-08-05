interface TypingIndicatorProps {
  message?: string;
}

/**
 * Beautiful typing indicator with animation
 */
export function TypingIndicator({ message = 'Đang suy nghĩ...' }: TypingIndicatorProps) {
  return (
    <div className="py-4 bg-gray-50 dark:bg-gray-800/50 animate-in fade-in duration-300">
      <div className="max-w-4xl mx-auto px-4">
        <div className="flex gap-4">
          {/* Avatar */}
          <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center text-white shadow-lg shadow-green-500/20">
            <span className="text-base">⚖️</span>
          </div>

          {/* Typing indicator */}
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-semibold text-gray-900 dark:text-white">
                Trợ lý EPR
              </span>
            </div>

            <div className="flex items-center gap-3 py-3">
              {/* Animated dots */}
              <div className="flex gap-1">
                <span
                  className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce"
                  style={{ animationDelay: '0ms' }}
                />
                <span
                  className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce"
                  style={{ animationDelay: '150ms' }}
                />
                <span
                  className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce"
                  style={{ animationDelay: '300ms' }}
                />
              </div>
              <span className="text-sm text-gray-500 dark:text-gray-400">{message}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
