import React, { useState, useRef, useEffect } from 'react';
import type { SourceDocument } from '@/types';
import { Icon } from '@/components/UI/Icon';

export interface CitationLinkProps {
  index: number;
  document?: SourceDocument;
  citation?: Record<string, unknown>;
  onClick?: (index: number) => void;
  children?: React.ReactNode;
}

function textValue(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value) && value.length) return value.map((item) => String(item)).join(', ');
  return undefined;
}

function getDocumentMetadata(document?: SourceDocument, citation?: Record<string, unknown>) {
  const meta = document?.metadata || {};
  
  // Title
  const title =
    textValue(citation?.title) ||
    textValue(meta.Source_Title) ||
    textValue(meta.source_title) ||
    textValue(meta.document_title) ||
    textValue(meta.title) ||
    textValue(meta.ten_van_ban) ||
    textValue(meta.law_title) ||
    (meta.Document_Number ? `Văn bản số ${meta.Document_Number}` : undefined) ||
    textValue(meta.instrument_number) ||
    textValue(meta.law_ref) ||
    'Văn bản căn cứ pháp luật';

  // Anchor / Điều khoản
  const anchor =
    textValue(citation?.anchor) ||
    textValue(meta.legal_anchor) ||
    textValue(meta.anchor) ||
    textValue(meta.article_title) ||
    textValue(meta.article) ||
    [
      textValue(meta.Chuong || meta.chuong),
      textValue(meta.Dieu || meta.dieu),
      textValue(meta.Khoan || meta.khoan),
    ]
      .filter(Boolean)
      .join(' · ') ||
    undefined;

  // Status
  const rawStatus = (
    textValue(citation?.effective_status) ||
    textValue(meta.effective_status) ||
    textValue(meta.Effective_Status) ||
    'active'
  ).toLowerCase();

  const isExpired = rawStatus.includes('het') || rawStatus.includes('expired');
  const statusLabel = isExpired ? 'Hết hiệu lực' : 'Đang có hiệu lực';

  // Excerpt
  let excerpt =
    textValue(citation?.excerpt) ||
    textValue(document?.page_content) ||
    'Không có đoạn trích hiển thị.';
  // Clean raw artifacts like || or metadata headers
  excerpt = excerpt.replace(/\s*\|\|+\s*/g, ' ').replace(/^(\[[^\]]+\]\s*:\s*[^\n]+\n+)+/gi, '').trim();
  if (excerpt.length > 220) {
    excerpt = excerpt.slice(0, 215) + '...';
  }

  // URL
  const rawUrl =
    textValue(citation?.official_url) ||
    textValue(meta.official_url) ||
    textValue(meta.Source_URI) ||
    textValue(meta.source_uri) ||
    textValue(meta.url) ||
    textValue(meta.link);

  let officialUrl: string | undefined = undefined;
  if (rawUrl) {
    try {
      const parsed = new URL(rawUrl);
      if (['http:', 'https:'].includes(parsed.protocol)) {
        officialUrl = parsed.toString();
      }
    } catch {
      // Ignore invalid URL
    }
  }

  return { title, anchor, statusLabel, isExpired, excerpt, officialUrl };
}

export function CitationLink({ index, document, citation, onClick, children }: CitationLinkProps) {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLAnchorElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const openTimerRef = useRef<number | null>(null);
  const closeTimerRef = useRef<number | null>(null);

  const { title, anchor, statusLabel, isExpired, excerpt, officialUrl } = getDocumentMetadata(
    document,
    citation,
  );

  const handleMouseEnter = () => {
    if (closeTimerRef.current) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    openTimerRef.current = window.setTimeout(() => {
      setIsOpen(true);
    }, 120);
  };

  const handleMouseLeave = () => {
    if (openTimerRef.current) {
      window.clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
    closeTimerRef.current = window.setTimeout(() => {
      setIsOpen(false);
    }, 180);
  };

  useEffect(() => {
    return () => {
      if (openTimerRef.current) window.clearTimeout(openTimerRef.current);
      if (closeTimerRef.current) window.clearTimeout(closeTimerRef.current);
    };
  }, []);

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    onClick?.(index);
  };

  return (
    <span
      className="relative inline-block align-baseline"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <a
        ref={triggerRef}
        href={`#source-${index}`}
        onClick={handleClick}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        className="mx-0.5 inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-semibold text-[#006a63] bg-[#006a63]/10 hover:bg-[#006a63]/20 hover:text-[#005c55] border border-[#006a63]/20 transition-all select-none shadow-2xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#006a63] no-underline cursor-pointer"
      >
        {children || `[${index}]`}
      </a>

      {isOpen && (
        <span
          ref={popoverRef}
          role="dialog"
          aria-label={`Chi tiết nguồn ${index}`}
          className="absolute bottom-full left-1/2 z-50 mb-2 block w-80 -translate-x-1/2 rounded-xl border border-slate-200/90 bg-white p-3.5 shadow-xl transition-all motion-safe:animate-[fadeIn_150ms_ease-out] text-left whitespace-normal"
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
        >
          {/* Header */}
          <span className="flex items-center justify-between gap-2 pb-2 border-b border-slate-100">
            <span className="inline-flex items-center gap-1 text-xs font-bold text-[#006a63]">
              <Icon name="book" size={12} />
              Nguồn trích dẫn [{index}]
            </span>
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                isExpired
                  ? 'bg-rose-50 text-rose-700 border border-rose-200'
                  : 'bg-emerald-50 text-emerald-700 border border-emerald-200'
              }`}
            >
              {statusLabel}
            </span>
          </span>

          {/* Title & Anchor */}
          <span className="mt-2 block">
            <span className="block text-xs font-bold leading-snug text-slate-900 line-clamp-2">
              {title}
            </span>
            {anchor && (
              <span className="mt-1 flex items-center gap-1 text-[11px] font-medium text-slate-600">
                <Icon name="fileText" size={11} className="shrink-0 text-slate-400" />
                <span className="truncate">{anchor}</span>
              </span>
            )}
          </span>

          {/* Excerpt Snippet */}
          {excerpt && (
            <span className="mt-2 block rounded bg-slate-50 p-2 text-[11px] leading-relaxed text-slate-600 line-clamp-3 border border-slate-100 italic">
              &ldquo;{excerpt}&rdquo;
            </span>
          )}

          {/* Footer Actions */}
          <span className="mt-3 flex items-center justify-between gap-2 pt-2 border-t border-slate-100 text-xs">
            <button
              type="button"
              onClick={handleClick}
              className="font-semibold text-[#006a63] hover:text-[#005c55] hover:underline"
            >
              Xem chi tiết trong ngăn ➔
            </button>
            {officialUrl && (
              <a
                href={officialUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-slate-500 hover:text-slate-800"
              >
                <span>Văn bản gốc</span>
                <Icon name="externalLink" size={11} />
              </a>
            )}
          </span>

          {/* Popover Arrow */}
          <span className="absolute top-full left-1/2 -mt-px block -translate-x-1/2 border-4 border-transparent border-t-white drop-shadow-sm pointer-events-none" />
        </span>
      )}
    </span>
  );
}
