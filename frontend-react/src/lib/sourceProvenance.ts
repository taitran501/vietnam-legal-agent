import type { SourceDocument, SourceSnapshot } from '@/types';

/** Convert the persisted/source-snapshot contract into the legacy document shape used by the drawer. */
export function sourceSnapshotToDocument(source: SourceSnapshot, index = 0): SourceDocument {
  const citationIndex = source.citation_index || index + 1;
  const sourceId = source.source_id || `source-${citationIndex}`;
  return {
    page_content: source.excerpt || '',
    document_id: source.chunk_id || sourceId,
    source: source.source_kind === 'official_web' ? 'web' : source.source_kind || 'legal',
    metadata: {
      citation_index: citationIndex,
      citation_indices: source.citation_indices,
      source_id: sourceId,
      chunk_id: source.chunk_id,
      Source_Title: source.title,
      source_title: source.title,
      document_title: source.title,
      Document_Number: source.instrument_number,
      instrument_number: source.instrument_number,
      legal_anchor: source.anchor,
      anchor: source.anchor,
      Pages: source.page,
      Source_Start: source.offset_start,
      Source_End: source.offset_end,
      official_url: source.official_url,
      Source_URI: source.official_url,
      source_kind: source.source_kind,
      authority: source.authority,
      effective_status: source.effective_status,
      effective_from: source.effective_from,
      effective_to: source.effective_to,
      amendment_relationship: source.amendment_relationship,
      active_source_document_id: source.active_source_document_id,
      active_source_pages: source.active_source_pages,
      amendment_resolution_status: source.amendment_resolution_status,
      amendment_operations: source.amendment_operations,
      current_law_support: source.current_law_support,
      corpus_as_of_date: source.corpus_as_of_date,
    },
  };
}

export function sourceDocumentsFromSnapshots(sources: SourceSnapshot[] | undefined): SourceDocument[] {
  return (sources || []).map((source, index) => sourceSnapshotToDocument(source, index));
}
