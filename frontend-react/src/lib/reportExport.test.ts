import { describe, expect, it } from 'vitest';
import { buildPreliminaryReport } from './reportExport';

describe('buildPreliminaryReport', () => {
  it('includes the disclaimer, result, and source metadata', () => {
    const report = buildPreliminaryReport({
      answer: 'Theo Điều 34 [1], người lao động cần được báo trước theo luật.',
      timestamp: '2026-08-15T10:00:00Z',
      workflow: {
        outcome: 'completed',
        result_type: 'assessment',
        corpus_as_of_date: '2026-07-01',
        assessment: { conclusion: 'Đã xem xét sơ bộ tình huống theo nguồn được dẫn' },
      },
      documents: [{
        page_content: 'Thời gian thử việc được quy định trong Bộ luật Lao động.',
        document_id: 'labor-25',
        metadata: { Dieu: 'Điều 34', source: 'Bộ luật Lao động 2019', official_url: 'https://vbpl.vn/example' },
      }],
    });

    expect(report).toContain('không phải ý kiến tư vấn pháp lý');
    expect(report).toContain('Đánh giá sơ bộ');
    expect(report).toContain('Điều 34');
    expect(report).toContain('https://vbpl.vn/example');
    expect(report).toContain('2026-07-01');
  });
});
