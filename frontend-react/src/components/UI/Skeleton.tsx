import { cn } from '@/lib/cn';

interface SkeletonProps {
  className?: string;
  count?: number;
}

/**
 * Skeleton loading component with shimmer effect
 */
export function Skeleton({ className, count = 1 }: SkeletonProps) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={cn(
            'animate-pulse rounded-md bg-gray-200 dark:bg-gray-700',
            className
          )}
        />
      ))}
    </>
  );
}

/**
 * Message skeleton for loading chat messages
 */
export function MessageSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-6 p-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="h-8 w-8 rounded-full flex-shrink-0" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Session list skeleton for sidebar
 */
export function SessionSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-2 p-2">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className="h-14 w-full rounded-lg" />
      ))}
    </div>
  );
}
