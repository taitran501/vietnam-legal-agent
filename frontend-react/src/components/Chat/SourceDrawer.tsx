import { useEffect, useRef } from 'react';
import type { SourceDocument } from '@/types';
import { Drawer } from '@/components/UI/Drawer';
import { Icon } from '@/components/UI/Icon';
import { previewNotice } from '@/lib/userCopy';

interface SourceDrawerProps {
  citations?: Array<Record<string, unknown>>;
  documents: SourceDocument[];
  focusIndex?: number;
  isOpen: boolean;
  onClose: () => void;
  preview?: boolean;
}

function textValue(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value) && value.length) return value.map((item) => String(item)).join(', ');
  return undefined;
}

const genericSourceLabels = new Set([
  'legal',
  'web',
  'official_web',
  'cache',
  'error',
  'hệ thống văn bản',
  'pháp điển & luật quốc gia',
  'cơ sở dữ liệu pháp luật quốc gia',
  'vietnamese legal corpus',
]);

function metadataValue(document: SourceDocument, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = textValue(document.metadata?.[key]);
    if (value && value !== 'Chưa có trong metadata' && value.toLowerCase() !== 'unknown') {
      return value.replace(/\s*\|\|+\s*/g, ' · ').replace(/\s+/g, ' ').trim();
    }
  }
  return undefined;
}

function documentTitle(document: SourceDocument): string {
  const explicit = metadataValue(document, [
    'Source_Title',
    'source_title',
    'document_title',
    'Document_Title',
    'title',
    'ten_van_ban',
    'law_title',
  ]);
  if (explicit && !genericSourceLabels.has(explicit.toLowerCase())) return explicit;
  const instrument = metadataValue(document, ['Document_Number', 'instrument_number', 'number']);
  if (instrument) return `Văn bản số ${instrument}`;
  const legacyLabel = metadataValue(document, ['law_ref', 'source']);
  if (legacyLabel && !genericSourceLabels.has(legacyLabel.toLowerCase())) return legacyLabel;
  return 'Chưa xác định văn bản';
}

function documentLawName(document: SourceDocument): string | undefined {
  return metadataValue(document, ['law_ref', 'source', 'topic', 'subject']);
}

function documentAnchor(document: SourceDocument): string | undefined {
  const explicit = metadataValue(document, ['legal_anchor', 'anchor', 'article_title', 'article']);
  if (explicit) return explicit;
  const values = [
    metadataValue(document, ['Chuong', 'chuong', 'chapter']),
    metadataValue(document, ['Dieu', 'dieu']),
    metadataValue(document, ['Khoan', 'khoan']),
    metadataValue(document, ['Diem', 'diem']),
  ].filter(Boolean);
  return values.length ? values.join(' · ') : undefined;
}

function documentUrl(document: SourceDocument): string | undefined {
  const value = metadataValue(document, ['official_url', 'Source_URI', 'source_uri', 'url', 'source_url', 'link']);
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

function cleanExcerptText(raw: string): string {
  if (!raw) return 'Không có đoạn trích hiển thị.';
  // Defensive cleanup for legacy API payloads that flattened metadata fields
  // with ``||`` before the canonical source snapshot contract was introduced.
  let text = raw.replace(/\s*\|\|+\s*/g, '\n\n');
  // Strip raw ASCII headers like [CHỦ ĐỀ]: ... | [ĐỀ MỤC]: ... \n\n
  text = text.replace(/^(\[[^\]]+\]\s*:\s*[^|\n]+\s*\|\s*)+/gi, '');
  text = text.replace(/^(\[[^\]]+\]\s*:\s*[^\n]+\n+)+/gi, '');
  return text.trim() || raw.trim();
}

export function SourceDrawer({ citations = [], documents, focusIndex, isOpen, onClose, preview = false }: SourceDrawerProps) {
  const sourceRefs = useRef(new Map<number, HTMLElement>());

  useEffect(() => {
    if (!isOpen || !focusIndex) return;
    const timer = window.setTimeout(() => {
      const source = sourceRefs.current.get(focusIndex);
      source?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      source?.focus({ preventScroll: true });
    }, 40);
    return () => window.clearTimeout(timer);
  }, [focusIndex, isOpen]);

  return (
    <Drawer
      description="Đối chiếu nội dung tư vấn trực tiếp với các điều khoản pháp luật được trích dẫn."
      isOpen={isOpen}
      onClose={onClose}
      title="Nguồn tham khảo"
    >
      <div className="space-y-4 p-4 sm:p-5">
        {preview && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-xs leading-5 text-amber-900" role="status">
            {previewNotice}
          </div>
        )}

        {documents.map((document, index) => {
          const citationIndex = Number(metadataValue(document, ['citation_index'])) || index + 1;
          const title = documentTitle(document);
          const lawName = documentLawName(document);
          const anchor = documentAnchor(document);
          const url = documentUrl(document);
          const instrument = metadataValue(document, ['Document_Number', 'instrument_number']);
          const page = metadataValue(document, ['Pages', 'page']);
          const effectiveStatus = metadataValue(document, ['effective_status', 'Effective_Status']) || 'unknown';
          const effectiveFrom = metadataValue(document, ['effective_from', 'Effective_From']);
          const cleanText = cleanExcerptText(document.page_content || '');
          const excerpt = cleanText.slice(0, 1500);
          const sourceId = metadataValue(document, ['source_id', 'Document_Id', 'document_id']) || document.document_id || `doc-${citationIndex}`;
          const hasCanonicalTitle = title !== 'Chưa xác định văn bản';

          return (
            <article
              className="group rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition-all hover:border-teal-600/40 hover:shadow-md focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
              id={`source-${citationIndex}`}
              key={document.document_id || `${title}-${index}`}
              ref={(node) => {
                if (node) sourceRefs.current.set(citationIndex, node);
                else sourceRefs.current.delete(citationIndex);
              }}
              tabIndex={-1}
            >
              {/* Header with index, title, and key pills */}
              <div className="flex items-start gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-xs font-bold text-teal-700 ring-1 ring-teal-600/20">
                  {citationIndex}
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="text-[15px] font-bold leading-snug text-slate-900">
                    {title}
                  </h3>
                  {!hasCanonicalTitle && (
                    <p className="mt-1 text-xs text-amber-700">
                      Chưa có đủ metadata để định danh văn bản; đoạn trích vẫn được giữ để đối chiếu.
                    </p>
                  )}

                  {/* Metadata Tag Pills - only render what actually exists */}
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                    {lawName && lawName !== title && (
                      <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-700">
                        <Icon name="book" size={11} />
                        {lawName}
                      </span>
                    )}
                    {anchor && anchor !== title && (
                      <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-slate-600">
                        <Icon name="fileText" size={11} />
                        {anchor}
                      </span>
                    )}
                    {effectiveStatus === 'active' && (
                      <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700 ring-1 ring-emerald-600/20">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                        Đang hiệu lực
                      </span>
                    )}
                    {effectiveStatus === 'superseded' && (
                      <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 font-medium text-amber-800 ring-1 ring-amber-600/20">
                        <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                        Đã sửa đổi / bổ sung
                      </span>
                    )}
                    {effectiveStatus === 'unknown' && (
                      <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-slate-600">
                        Trạng thái chưa xác định
                      </span>
                    )}
                    {instrument && (
                      <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-600">
                        Số: {instrument}
                      </span>
                    )}
                    {page && (
                      <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-600">
                        Trang {page}
                      </span>
                    )}
                    {effectiveFrom && (
                      <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-600">
                        Từ {effectiveFrom}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Clean Law Provision Quote */}
              <div className="mt-3 rounded-lg border border-slate-100 bg-slate-50/70 p-3.5 text-[13px] leading-relaxed text-slate-700">
                <p className="whitespace-pre-wrap font-sans">
                  {excerpt}
                  {cleanText.length > excerpt.length ? '…' : ''}
                </p>
              </div>

              {/* External Official Link button */}
              <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2.5">
                {url ? (
                  <a
                    className="inline-flex items-center gap-1.5 text-xs font-semibold text-teal-700 transition-colors hover:text-teal-900 hover:underline"
                    href={url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    Mở nguồn
                    <Icon name="chevronRight" size={14} />
                  </a>
                ) : <span className="text-[11px] text-slate-500">Chưa có liên kết chính thức</span>}
                <span className="text-[11px] font-mono text-slate-600">
                  Mã nguồn: {sourceId}
                </span>
              </div>
            </article>
          );
        })}

        {documents.length === 0 && citations.length > 0 && (
          <div className="space-y-2.5">
            {citations.map((citation, index) => (
              <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" key={index}>
                <div className="flex items-start gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-xs font-bold text-teal-700 ring-1 ring-teal-600/20">
                    {textValue(citation.index) || index + 1}
                  </span>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">
                      {textValue(citation.label) || textValue(citation.document_id) || 'Căn cứ pháp luật'}
                    </h3>
                    {textValue(citation.anchor) && (
                      <p className="mt-1 text-xs text-slate-500">{textValue(citation.anchor)}</p>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}

        {documents.length === 0 && citations.length === 0 && (
          <div className="rounded-2xl border border-dashed border-slate-200 px-5 py-12 text-center">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400">
              <Icon name="scale" size={20} />
            </div>
            <p className="mt-3 text-sm font-semibold text-slate-700">Chưa có căn cứ trích dẫn</p>
            <p className="mt-1 text-xs text-slate-400">
              Khi câu trả lời có viện dẫn điều luật cụ thể, các nguồn sẽ hiển thị tại đây.
            </p>
          </div>
        )}
      </div>
    </Drawer>
  );
}
