import { describe, expect, it } from 'vitest';
import { sourceDocumentsFromSnapshots } from './sourceProvenance';

describe('source provenance adapters', () => {
  it('keeps parent source identity and chunk identity when restoring a session', () => {
    const [document] = sourceDocumentsFromSnapshots([
      {
        citation_index: 2,
        source_id: 'nd-318-2026',
        chunk_id: 'chunk-1',
        title: 'Nghị định số 318/2026/NĐ-CP',
        instrument_number: '318/2026/NĐ-CP',
        anchor: 'Điều 1',
        excerpt: 'Điều 1 quy định phạm vi áp dụng.',
        source_kind: 'legal_corpus',
      },
    ]);

    expect(document.document_id).toBe('chunk-1');
    expect(document.metadata.source_id).toBe('nd-318-2026');
    expect(document.metadata.Source_Title).toBe('Nghị định số 318/2026/NĐ-CP');
    expect(document.metadata.Document_Number).toBe('318/2026/NĐ-CP');
    expect(document.metadata.legal_anchor).toBe('Điều 1');
    expect(document.page_content).toBe('Điều 1 quy định phạm vi áp dụng.');
  });
});
