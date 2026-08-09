import type { SourceDocument } from '@/types';
import { Icon } from '@/components/UI/Icon';

interface SourceDocumentsProps {
  citations?: Array<Record<string, unknown>>;
  documents: SourceDocument[];
  onOpen: (documents: SourceDocument[], citations: Array<Record<string, unknown>>) => void;
}

export function SourceDocuments({ citations = [], documents, onOpen }: SourceDocumentsProps) {
  const count = documents.length || citations.length;
  if (count === 0) return null;

  return (
    <button
      className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-lg border border-[#bdc9c6] bg-white px-3 py-2 text-sm font-semibold text-[#006a63] transition-colors hover:border-[#0f766e] hover:bg-[#f1f4f3] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0f766e]"
      onClick={() => onOpen(documents, citations)}
      type="button"
    >
      <Icon name="source" size={16} />
      Xem {count} nguồn tham khảo
      <Icon name="chevronRight" size={15} />
    </button>
  );
}
