import { Icon } from '@/components/UI/Icon';
import { ReasoningBlock } from './ReasoningBlock';
import type { WorkflowStep } from '@/types';

interface TypingIndicatorProps {
  message?: string;
  steps?: WorkflowStep[];
}

export function TypingIndicator({ message = 'Đang hiểu yêu cầu…', steps = [] }: TypingIndicatorProps) {
  return (
    <article className="px-4 py-5 motion-safe:animate-[messageIn_240ms_ease-out] sm:px-6">
      <div className="mx-auto w-full max-w-[820px]">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#0f766e] text-white">
            <Icon name="scale" size={17} />
          </span>
          <p className="text-sm font-semibold text-[#005c55]">Trợ lý pháp lý</p>
        </div>
        <div className="ml-0 mt-2 sm:ml-[42px]">
          <ReasoningBlock isStreaming statusMessage={message} steps={steps} />
        </div>
      </div>
    </article>
  );
}
