import { useEffect, useRef } from 'react';
import type { SourceDocument } from '@/types';
import { Drawer } from '@/components/UI/Drawer';
import { Icon } from '@/components/UI/Icon';

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

function metadataValue(document: SourceDocument, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = textValue(document.metadata?.[key]);
    if (value) return value;
  }
  return undefined;
}

function documentTitle(document: SourceDocument, index: number): string {
  return (
    metadataValue(document, ['source_title', 'Source_Title', 'title', 'document_title', 'ten_van_ban', 'source', 'file_name', 'Document_Number']) ||
    `Nguồn pháp lý ${index + 1}`
  );
}

function documentAnchor(document: SourceDocument): string | undefined {
  const explicit = metadataValue(document, ['legal_anchor', 'anchor']);
  if (explicit) return explicit;
  const values = [
    metadataValue(document, ['Chuong', 'chuong']),
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
      description="Đối chiếu nội dung trả lời với các đoạn văn bản mà hệ thống đã sử dụng."
      isOpen={isOpen}
      onClose={onClose}
      title="Nguồn tham khảo"
    >
      <div className="space-y-3 p-4 sm:p-5">
        {preview && (
          <div className="rounded-lg border border-[#d7a65a] bg-[#fff8ea] p-3 text-xs leading-5 text-[#714b18]" role="status">
            Bản thử nghiệm: thông tin có thể thay đổi sau khi kho văn bản được phê duyệt.
          </div>
        )}
        {documents.map((document, index) => {
          const citationIndex = Number(metadataValue(document, ['citation_index'])) || index + 1;
          const anchor = documentAnchor(document);
          const url = documentUrl(document);
          const instrument = metadataValue(document, ['Document_Number', 'instrument_number']);
          const page = metadataValue(document, ['Pages', 'page']);
          const effectiveStatus = metadataValue(document, ['effective_status', 'Effective_Status']) || 'unknown';
          const effectiveFrom = metadataValue(document, ['effective_from', 'Effective_From']);
          const asOf = metadataValue(document, ['corpus_as_of_date', 'Corpus_As_Of_Date']) || 'Chưa được pháp lý phê duyệt';
          const amendmentStatus = metadataValue(document, ['amendment_resolution_status', 'Amendment_Resolution_Status']);
          const activeSource = metadataValue(document, ['active_source_document_id', 'Active_Source_Document_Id']);
          const activePages = metadataValue(document, ['active_source_pages', 'Active_Source_Pages']);
          const excerpt = (document.page_content || 'Nguồn này chưa có đoạn trích để hiển thị.').slice(0, 1400);
          return (
            <article
              className="rounded-lg border border-[#d9e1df] bg-white p-4 outline-none focus:border-[#0f766e] focus:ring-2 focus:ring-[#0f766e]/20"
              id={`source-${citationIndex}`}
              key={document.document_id || `${documentTitle(document, index)}-${index}`}
              ref={(node) => {
                if (node) sourceRefs.current.set(citationIndex, node);
                else sourceRefs.current.delete(citationIndex);
              }}
              tabIndex={-1}
            >
              <div className="flex items-start gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[#e7eceb] text-xs font-semibold text-[#006a63]">
                  {citationIndex}
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-semibold leading-6 text-[#172033]">
                    {documentTitle(document, index)}
                  </h3>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[#667085]">
                    {anchor && (
                      <span className="inline-flex items-center gap-1">
                        <Icon name="fileText" size={13} />
                        {anchor}
                      </span>
                    )}
                    {instrument && <span>{instrument}</span>}
                    {page && <span>Trang {page}</span>}
                    <span className="rounded-full bg-[#e7eceb] px-2 py-0.5">{effectiveStatus === 'active' ? 'Đang hiệu lực' : effectiveStatus === 'unknown' ? 'Chưa xác định hiệu lực' : effectiveStatus}</span>
                    {effectiveFrom && <span>Hiệu lực từ {effectiveFrom}</span>}
                  </div>
                  <p className="mt-2 text-[11px] text-[#667085]">Kho văn bản tính đến: {asOf}</p>
                </div>
              </div>
              <blockquote className="mt-3 whitespace-pre-wrap rounded-md bg-[#f1f4f3] px-3 py-3 text-[13px] leading-6 text-[#3e4947]">
                {excerpt}{(document.page_content || '').length > excerpt.length ? '…' : ''}
              </blockquote>
              {(metadataValue(document, ['amendment_relationship', 'Amendment_Relationship']) || amendmentStatus || activeSource || document.document_id) && (
                <details className="mt-3 rounded-md border border-[#e5e9e7] px-3 py-2 text-xs text-[#667085]">
                  <summary className="cursor-pointer font-semibold text-[#53615e]">Thông tin đối chiếu</summary>
                  {metadataValue(document, ['amendment_relationship', 'Amendment_Relationship']) && <p className="mt-2">Quan hệ sửa đổi: {metadataValue(document, ['amendment_relationship', 'Amendment_Relationship'])}</p>}
                  {amendmentStatus && <p className="mt-1">Trạng thái đối chiếu sửa đổi: {amendmentStatus}</p>}
                  {activeSource && <p className="mt-1">Nguồn nội dung chính: {activeSource}{activePages ? ` · trang ${activePages}` : ''}</p>}
                  {document.document_id && <p className="mt-1">Mã nguồn: {document.document_id}</p>}
                </details>
              )}
              {url && (
                <a
                  className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-[#006a63] hover:underline"
                  href={url}
                  rel="noreferrer"
                  target="_blank"
                >
                  Mở nguồn
                  <Icon name="chevronRight" size={15} />
                </a>
              )}
            </article>
          );
        })}

        {documents.length === 0 && citations.length > 0 && (
          <div className="space-y-2">
            {citations.map((citation, index) => (
              <article className="rounded-lg border border-[#d9e1df] bg-white p-4" key={index}>
                <div className="flex items-start gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[#e7eceb] text-xs font-semibold text-[#006a63]">
                    {textValue(citation.index) || index + 1}
                  </span>
                  <div>
                    <h3 className="text-sm font-semibold leading-6 text-[#172033]">
                      {textValue(citation.label) || textValue(citation.document_id) || 'Nguồn pháp lý'}
                    </h3>
                    {textValue(citation.anchor) && (
                      <p className="mt-1 text-xs text-[#667085]">{textValue(citation.anchor)}</p>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}

        {documents.length === 0 && citations.length === 0 && (
          <div className="rounded-lg border border-dashed border-[#bdc9c6] px-5 py-10 text-center">
            <Icon className="mx-auto text-[#6e7977]" name="source" size={28} />
            <p className="mt-3 text-sm font-medium text-[#3e4947]">Chưa có nguồn để hiển thị</p>
            <p className="mt-1 text-xs leading-5 text-[#667085]">
              Hệ thống sẽ chỉ mở bảng này khi câu trả lời có tài liệu đối chiếu.
            </p>
          </div>
        )}
      </div>
    </Drawer>
  );
}
