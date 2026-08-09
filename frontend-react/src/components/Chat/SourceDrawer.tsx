import type { SourceDocument } from '@/types';
import { Drawer } from '@/components/UI/Drawer';
import { Icon } from '@/components/UI/Icon';

interface SourceDrawerProps {
  citations?: Array<Record<string, unknown>>;
  documents: SourceDocument[];
  isOpen: boolean;
  onClose: () => void;
}

function textValue(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number') return String(value);
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
    metadataValue(document, ['title', 'document_title', 'ten_van_ban', 'source', 'file_name']) ||
    textValue(document.source) ||
    `Nguồn pháp lý ${index + 1}`
  );
}

function documentAnchor(document: SourceDocument): string | undefined {
  const values = [
    metadataValue(document, ['Chuong', 'chuong']),
    metadataValue(document, ['Dieu', 'dieu']),
    metadataValue(document, ['Khoan', 'khoan']),
    metadataValue(document, ['Diem', 'diem']),
  ].filter(Boolean);
  return values.length ? values.join(' · ') : undefined;
}

function documentUrl(document: SourceDocument): string | undefined {
  const value = metadataValue(document, ['url', 'source_url', 'link']);
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

export function SourceDrawer({ citations = [], documents, isOpen, onClose }: SourceDrawerProps) {
  return (
    <Drawer
      description="Đối chiếu nội dung trả lời với các đoạn văn bản mà hệ thống đã sử dụng."
      isOpen={isOpen}
      onClose={onClose}
      title="Nguồn tham khảo"
    >
      <div className="space-y-3 p-4 sm:p-5">
        {documents.map((document, index) => {
          const anchor = documentAnchor(document);
          const url = documentUrl(document);
          const score = typeof document.score === 'number' ? document.score : null;
          return (
            <article
              className="rounded-lg border border-[#d9e1df] bg-white p-4"
              key={document.document_id || `${documentTitle(document, index)}-${index}`}
            >
              <div className="flex items-start gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[#e7eceb] text-xs font-semibold text-[#006a63]">
                  {index + 1}
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
                    {score !== null && score >= 0 && score <= 1 && (
                      <span>Độ liên quan {Math.round(score * 100)}%</span>
                    )}
                  </div>
                </div>
              </div>
              <blockquote className="mt-3 whitespace-pre-wrap rounded-md bg-[#f1f4f3] px-3 py-3 text-[13px] leading-6 text-[#3e4947]">
                {document.page_content || 'Nguồn này chưa có đoạn trích để hiển thị.'}
              </blockquote>
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
