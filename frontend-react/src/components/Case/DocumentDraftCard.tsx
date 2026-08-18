import { useState } from 'react';
import { Icon } from '@/components/UI/Icon';

export interface DocumentDraftData {
  draft_id: string;
  document_type: string;
  title: string;
  plain_text: string;
  legal_basis: string;
  instructions: string[];
}

interface DocumentDraftCardProps {
  draft: DocumentDraftData;
}

export function DocumentDraftCard({ draft }: DocumentDraftCardProps) {
  const [downloading, setDownloading] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleDownloadDocx = async () => {
    setDownloading(true);
    try {
      const response = await fetch('/api/v1/documents/export-docx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: draft.title || 'Van_ban_phap_ly',
          content: draft.plain_text,
        }),
      });
      if (!response.ok) throw new Error('Không thể tạo file Word');

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(draft.title || 'van_ban_phap_ly').toLowerCase().replace(/\s+/g, '_')}.docx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch {
      alert('Không thể tải file Word lúc này. Bạn có thể sao chép nội dung văn bản.');
    } finally {
      setDownloading(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(draft.plain_text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="my-4 overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-4">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal-100 text-teal-800 ring-1 ring-teal-600/20">
            <Icon name="fileText" size={18} />
          </span>
          <div>
            <h4 className="text-sm font-bold text-slate-900">{draft.title}</h4>
            <p className="text-xs text-slate-500">{draft.legal_basis}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
            onClick={handleCopy}
            type="button"
          >
            <Icon name={copied ? 'check' : 'copy'} size={13} />
            {copied ? 'Đã chép' : 'Sao chép văn bản'}
          </button>
          <button
            className="inline-flex items-center gap-1.5 rounded-lg bg-teal-700 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-teal-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600"
            disabled={downloading}
            onClick={handleDownloadDocx}
            type="button"
          >
            <Icon name="download" size={13} />
            {downloading ? 'Đang tạo...' : 'Tải file Word (.docx) chuẩn Tòa án'}
          </button>
        </div>
      </div>

      {/* Text preview box */}
      <div className="mt-4 max-h-72 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50/70 p-4 font-serif-legal text-xs leading-relaxed text-slate-800">
        <pre className="whitespace-pre-wrap font-sans">{draft.plain_text}</pre>
      </div>

      {/* Instructions list */}
      {draft.instructions && draft.instructions.length > 0 && (
        <div className="mt-4 rounded-xl bg-teal-50/50 p-3.5 text-xs text-slate-700">
          <p className="font-bold text-teal-900">Hướng dẫn thủ tục tiếp theo:</p>
          <ol className="mt-1.5 list-inside list-decimal space-y-1">
            {draft.instructions.map((ins, i) => (
              <li key={i}>{ins}</li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
