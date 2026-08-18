import { useState } from 'react';
import type { CaseState, ChatMessage, SourceDocument } from '@/types';
import { formatTimestamp } from '@/lib/formatters';
import { MarkdownRenderer } from '@/utils/markdown';
import { MessageActions } from './MessageActions';
import { SourceDocuments } from './SourceDocuments';
import { WorkflowResultCard } from '@/components/Agent/WorkflowResultCard';
import { Icon } from '@/components/UI/Icon';

interface ChatMessageProps {
  message: ChatMessage;
  onOpenCase?: () => void;
  onContinueCase?: (facts: Record<string, string>, statuses: Record<string, 'user_confirmed' | 'document_verified' | 'unknown'>, taskType: CaseState['task_type']) => Promise<void>;
  onResearch?: () => void;
  onExport?: (message: ChatMessage) => void;
  onOpenSources: (documents: SourceDocument[], citations: Array<Record<string, unknown>>, focusIndex?: number, preview?: boolean) => void;
  onRegenerate?: () => void;
  webResearchReady: boolean;
}

const sourceLabels: Record<string, string> = {
  legal: 'Căn cứ pháp luật',
  chitchat: 'Hội thoại',
  web_search: 'Nguồn chính thức bên ngoài kho văn bản',
  cache: 'Câu trả lời đã xác minh',
  follow_up: 'Đang làm rõ thông tin',
};

export function ChatMessageComponent({ message, onOpenCase, onContinueCase, onOpenSources, onRegenerate, onResearch, onExport, webResearchReady }: ChatMessageProps) {
  const isUser = message.role === 'user';
  const [copied, setCopied] = useState(false);

  if (isUser) {
    return (
      <article className="px-4 py-5 sm:px-6">
        <div className="mx-auto flex w-full max-w-[820px] justify-end">
          <div className="max-w-[88%] sm:max-w-[76%]">
            <div className="rounded-xl rounded-tr-sm border border-[#e1e6e4] bg-[#f1f4f3] px-4 py-3 text-[15px] leading-6 text-[#172033]">
              <p className="whitespace-pre-wrap break-words">{message.content}</p>
            </div>
            <p className="mt-1.5 text-right text-[11px] text-[#84908d]">{formatTimestamp(message.timestamp)}</p>
          </div>
        </div>
      </article>
    );
  }

  return (
    <article className="group px-4 py-5 motion-safe:animate-[messageIn_240ms_ease-out] sm:px-6">
      <div className="mx-auto w-full max-w-[820px]">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#0f766e] text-white">
            <Icon name="scale" size={17} />
          </span>
          <div>
            <p className="text-sm font-semibold text-[#005c55]">Trợ lý pháp lý</p>
            <p className="text-[11px] text-[#84908d]">{formatTimestamp(message.timestamp)}</p>
          </div>
        </div>

        <div className="ml-0 mt-3 sm:ml-[42px]">
          {message.status === 'stopped' && (
            <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-[#d7a65a] bg-[#fff8ea] px-2.5 py-1 text-xs font-semibold text-[#714b18]">
              <Icon name="alert" size={13} />
              Đã dừng theo yêu cầu · nội dung chưa hoàn chỉnh
            </div>
          )}
          <div className="legal-prose max-w-none text-[15px] leading-7 text-[#262d2c] sm:text-base">
            <MarkdownRenderer
              content={message.content}
              onCitationClick={(index) => {
                onOpenSources(
                  message.documents || [],
                  message.workflow?.citations || [],
                  index,
                  message.workflow?.preview,
                );
              }}
            />
          </div>

          <WorkflowResultCard
            onContinueCase={onContinueCase}
            onOpenCase={onOpenCase}
            onOpenSources={(focusIndex) => onOpenSources(message.documents || [], message.workflow?.citations || [], focusIndex, message.workflow?.preview)}
            onResearch={onResearch}
            onExport={() => onExport?.(message)}
            webResearchReady={webResearchReady}
            workflow={message.workflow}
          />
          <SourceDocuments
            citations={message.workflow?.citations}
            documents={message.documents || []}
            onOpen={(documents, citations) => onOpenSources(documents, citations, undefined, message.workflow?.preview)}
          />

          <div className="mt-3 flex min-h-8 flex-wrap items-center justify-between gap-2 border-t border-[#edf0ef] pt-2">
            <div className="text-[11px] text-[#667085]">
              {message.source && message.source !== 'error' && (
                <span>{sourceLabels[message.source] || 'Nguồn tham khảo'}</span>
              )}
            </div>
            <div className="opacity-100">
              <MessageActions
                copied={copied}
                message={message}
                onCopy={() => {
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 2000);
                }}
                onRegenerate={onRegenerate}
              />
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}
