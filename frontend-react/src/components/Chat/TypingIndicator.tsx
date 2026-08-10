import { Icon } from '@/components/UI/Icon';

interface TypingIndicatorProps {
  message?: string;
}

export function TypingIndicator({ message = 'Đang hiểu yêu cầu…' }: TypingIndicatorProps) {
  return (
    <article className="px-4 py-5 motion-safe:animate-[messageIn_240ms_ease-out] sm:px-6">
      <div className="mx-auto w-full max-w-[820px]">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#0f766e] text-white">
            <Icon name="scale" size={17} />
          </span>
          <p className="text-sm font-semibold text-[#005c55]">Trợ lý pháp lý</p>
        </div>
        <div className="ml-0 mt-3 flex items-center gap-3 sm:ml-[42px]" role="status">
          <span className="flex gap-1" aria-hidden="true">
            {[0, 1, 2].map((index) => (
              <span
                className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#80a7a1] motion-reduce:animate-none"
                key={index}
                style={{ animationDelay: `${index * 180}ms` }}
              />
            ))}
          </span>
          <span className="text-sm text-[#667085]">{message}</span>
        </div>
      </div>
    </article>
  );
}
