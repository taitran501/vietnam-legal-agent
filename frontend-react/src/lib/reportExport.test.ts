import { describe, expect, it } from 'vitest';
import { buildPreliminaryReport } from './reportExport';

describe('buildPreliminaryReport', () => {
  it('includes the disclaimer, unverified facts, result, and source metadata', () => {
    const report = buildPreliminaryReport({
      answer: 'Theo Điều 77 [1], cần thực hiện trách nhiệm tái chế.',
      timestamp: '2026-08-15T10:00:00Z',
      workflow: {
        outcome: 'completed',
        result_type: 'assessment',
        corpus_as_of_date: '2026-07-01',
        assessment: { conclusion: 'Có khả năng thuộc phạm vi EPR' },
        case_state: {
          task_type: 'assess_epr_obligation',
          status: 'ready',
          facts: { material: { value: 'nhựa', verified: false, source: 'user_turn' } },
          missing_facts: [],
        },
      },
      documents: [{
        page_content: 'Nhà sản xuất có trách nhiệm tái chế.',
        document_id: 'law-77',
        metadata: { Dieu: 'Điều 77', source: 'Nghị định 08/2022/NĐ-CP', official_url: 'https://vbpl.vn/example' },
      }],
    });

    expect(report).toContain('không phải ý kiến tư vấn pháp lý');
    expect(report).toContain('nhựa');
    expect(report).toContain('Điều 77');
    expect(report).toContain('https://vbpl.vn/example');
    expect(report).toContain('2026-07-01');
  });
});
