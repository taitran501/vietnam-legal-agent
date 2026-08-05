import { useState } from 'react';
import type { SourceDocument } from '@/types';
import { cn } from '@/lib/cn';

interface SourceDocumentsProps {
  documents: SourceDocument[];
}

/**
 * Expandable source documents section
 */
export function SourceDocuments({ documents }: SourceDocumentsProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (documents.length === 0) return null;

  return (
    <div className="mt-3">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
      >
        <svg
          className={cn(
            'w-4 h-4 transition-transform duration-200',
            isExpanded ? 'rotate-90' : ''
          )}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 5l7 7-7 7"
          />
        </svg>
        <span>{documents.length} tài liệu tham khảo</span>
      </button>

      {isExpanded && (
        <div className="mt-2 space-y-2">
          {documents.map((doc, index) => (
            <div
              key={index}
              className="p-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm"
            >
              {/* Document metadata */}
              {doc.metadata && (
                <div className="flex flex-wrap gap-2 mb-2">
                  {doc.metadata.Dieu && (
                    <span className="px-2 py-0.5 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 rounded text-xs font-medium">
                      {doc.metadata.Dieu}
                    </span>
                  )}
                  {doc.metadata.Chuong && (
                    <span className="px-2 py-0.5 bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-400 rounded text-xs font-medium">
                      {doc.metadata.Chuong}
                    </span>
                  )}
                </div>
              )}

              {/* Document content preview */}
              <p className="text-gray-700 dark:text-gray-300 line-clamp-3">
                {doc.page_content.slice(0, 200)}
                {doc.page_content.length > 200 ? '...' : ''}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
