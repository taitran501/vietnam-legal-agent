import type { SourceDocument, WorkflowMetadata } from '@/types';

export interface PreliminaryReportInput {
  answer: string;
  timestamp: string;
  workflow: WorkflowMetadata;
  documents: SourceDocument[];
}

function metadataValue(document: SourceDocument, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = document.metadata?.[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number') return String(value);
  }
  return undefined;
}

function documentTitle(document: SourceDocument, index: number): string {
  return metadataValue(document, ['source_title', 'title', 'document_title', 'source', 'file_name', 'Document_Number'])
    || `Nguồn pháp lý ${index + 1}`;
}

function documentAnchor(document: SourceDocument): string {
  return metadataValue(document, ['legal_anchor', 'anchor'])
    || [
      metadataValue(document, ['Chuong', 'chuong']),
      metadataValue(document, ['Dieu', 'dieu']),
      metadataValue(document, ['Khoan', 'khoan']),
      metadataValue(document, ['Diem', 'diem']),
    ].filter(Boolean).join(' · ')
    || 'Chưa có điều/khoản trong metadata';
}

function factText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object' && 'value' in value) return String((value as { value?: unknown }).value || '');
  return String(value || '');
}

export function buildPreliminaryReport({ answer, timestamp, workflow, documents }: PreliminaryReportInput): string {
  const lines = [
    'BÁO CÁO SƠ BỘ',
    '===================',
    'Tài liệu này chỉ hỗ trợ đối chiếu ban đầu, không phải ý kiến tư vấn pháp lý hoặc quyết định tuân thủ cuối cùng.',
    `Thời điểm tạo: ${timestamp}`,
    `Trạng thái workflow: ${workflow.outcome || 'chưa xác định'}`,
    `Corpus cập nhật đến: ${workflow.corpus_as_of_date || 'chưa có ngày được phê duyệt'}`,
    '',
    '1. Kết quả',
    '----------',
    answer.trim() || 'Không có nội dung kết quả.',
  ];

  if (workflow.assessment) {
    lines.push('', '2. Đánh giá sơ bộ', '-----------------', `Kết luận: ${String(workflow.assessment.conclusion || 'Chưa có kết luận')}`);
    const reasons = workflow.assessment.reasons;
    if (Array.isArray(reasons) && reasons.length) {
      lines.push('Lý do:');
      for (const reason of reasons) lines.push(`- ${String((reason as Record<string, unknown>).claim || reason)}`);
    }
  }

  if (workflow.checklist?.length) {
    lines.push('', '2. Danh sách việc cần làm (Checklist tuân thủ)', '----------------------------------------------');
    lines.push('| STT | Hạng mục thực hiện | Thao tác chi tiết | Căn cứ pháp lý |');
    lines.push('|---|---|---|---|');
    workflow.checklist.forEach((item, index) => {
      const itemTitle = String(item.item || 'Hạng mục cần thực hiện').replace(/\|/g, '-');
      const actionText = (item.action ? String(item.action) : 'Theo quy định').replace(/\|/g, '-');
      const evidence = Array.isArray(item.evidence_indices) && item.evidence_indices.length
        ? item.evidence_indices.map((val) => `[${String(val)}]`).join(' ')
        : 'Theo văn bản luật';
      lines.push(`| ${index + 1} | ${itemTitle} | ${actionText} | ${evidence} |`);
    });
  }

  const facts = Object.entries(workflow.case_state?.facts || {}).filter(([, value]) => factText(value).trim());
  if (facts.length) {
    lines.push('', '3. Thông tin doanh nghiệp đã cung cấp', '--------------------------------------', 'Các dữ kiện dưới đây do người dùng cung cấp và chưa được xác minh độc lập:');
    for (const [key, value] of facts) lines.push(`- ${key}: ${factText(value)}`);
  }

  lines.push('', '4. Căn cứ tham khảo', '--------------------');
  if (documents.length) {
    documents.forEach((document, index) => {
      lines.push(`[${index + 1}] ${documentTitle(document, index)}`);
      lines.push(`    Điều/khoản: ${documentAnchor(document)}`);
      lines.push(`    Trích đoạn: ${(document.page_content || 'Chưa có trích đoạn').trim()}`);
      const url = metadataValue(document, ['official_url', 'source_uri', 'url', 'source_url', 'link']);
      if (url) lines.push(`    Liên kết chính thức: ${url}`);
    });
  } else if (workflow.citations?.length) {
    for (const citation of workflow.citations) {
      lines.push(`[${String(citation.index || '')}] ${String(citation.label || citation.document_id || 'Nguồn pháp lý')}`);
    }
  } else {
    lines.push('Chưa có nguồn tham khảo để hiển thị.');
  }

  lines.push('', 'Ghi chú: Cần đối chiếu bản văn chính thức và phê duyệt nội bộ trước khi sử dụng cho quyết định quan trọng.');
  return `${lines.join('\n')}\n`;
}

export function downloadPreliminaryReport(input: PreliminaryReportInput): void {
  const blob = new Blob([buildPreliminaryReport(input)], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  const stamp = input.timestamp.replace(/[^0-9]+/g, '-').replace(/^-|-$/g, '') || 'report';
  anchor.href = url;
  anchor.download = `epr-bao-cao-so-bo-${stamp}.txt`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
