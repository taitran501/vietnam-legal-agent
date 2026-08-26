import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SourceDrawer } from './SourceDrawer';

describe('SourceDrawer', () => {
  it('renders legal anchors and closes from its explicit action', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <SourceDrawer
        documents={[
          {
            page_content: 'Nhà sản xuất, nhập khẩu có trách nhiệm tái chế sản phẩm, bao bì.',
            document_id: 'law-77',
            score: 0.91,
            source: 'legal',
            metadata: {
              Dieu: 'Điều 77',
              source: 'Nghị định 08/2022/NĐ-CP',
              official_url: 'https://vanban.chinhphu.vn/?docid=205092&pageid=27160',
            },
          },
        ]}
        isOpen
        onClose={onClose}
      />
    );

    expect(screen.getByRole('dialog', { name: 'Nguồn tham khảo' })).toBeInTheDocument();
    expect(screen.getByText('Nghị định 08/2022/NĐ-CP')).toBeInTheDocument();
    expect(screen.getByText(/Điều 77/)).toBeInTheDocument();
    expect(screen.queryByText(/Chưa có trong metadata/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Mở nguồn/i })).toHaveAttribute('href', 'https://vanban.chinhphu.vn/?docid=205092&pageid=27160');
    expect(screen.queryByText(/Thông tin được cập nhật đến/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Đóng' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('focuses the cited source while keeping the complete source list visible', async () => {
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    render(
      <SourceDrawer
        documents={[
          { page_content: 'Nguồn một', document_id: 'one', metadata: { citation_index: 1, source: 'Nguồn 1' } },
          { page_content: 'Nguồn hai', document_id: 'two', metadata: { citation_index: 2, source: 'Nguồn 2' } },
        ]}
        focusIndex={2}
        isOpen
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Nguồn 1')).toBeInTheDocument();
    expect(screen.getByText('Nguồn 2')).toBeInTheDocument();
    await vi.waitFor(() => expect(document.activeElement).toHaveAttribute('id', 'source-2'));
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it('shows the preview notice only when the source drawer is opened in preview mode', () => {
    const { rerender } = render(
      <SourceDrawer documents={[]} isOpen onClose={vi.fn()} />,
    );
    expect(screen.queryByText(/Bản thử nghiệm:/)).not.toBeInTheDocument();
    rerender(<SourceDrawer documents={[]} isOpen onClose={vi.fn()} preview />);
    expect(screen.getByText(/Bản thử nghiệm:/)).toBeInTheDocument();
  });

  it('renders canonical document identity instead of using the article chunk as the title', () => {
    render(
      <SourceDrawer
        documents={[
          {
            page_content: '[CHỦ ĐỀ]: Văn bản | [CĂN CỨ VĂN BẢN]: raw\n\nĐiều 1 quy định phạm vi áp dụng.',
            document_id: 'chunk-1',
            metadata: {
              source_id: 'nd-318-2026',
              chunk_id: 'chunk-1',
              Source_Title: 'Nghị định số 318/2026/NĐ-CP',
              Document_Number: '318/2026/NĐ-CP',
              legal_anchor: 'Điều 1',
              citation_index: 1,
              effective_status: 'unknown',
            },
          },
        ]}
        isOpen
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Nghị định số 318/2026/NĐ-CP' })).toBeInTheDocument();
    expect(screen.getByText('Điều 1 quy định phạm vi áp dụng.')).toBeInTheDocument();
    expect(screen.getByText('Trạng thái chưa xác định')).toBeInTheDocument();
    expect(screen.getByText('Mã nguồn: nd-318-2026')).toBeInTheDocument();
    expect(screen.queryByText(/\[CHỦ ĐỀ\]/)).not.toBeInTheDocument();
  });

  it('shows an explicit missing-source state instead of a fabricated source title or link', () => {
    render(
      <SourceDrawer
        documents={[{ page_content: 'Đoạn trích chưa có metadata.', document_id: 'chunk-unknown', metadata: {} }]}
        isOpen
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Chưa xác định văn bản' })).toBeInTheDocument();
    expect(screen.getByText(/Chưa có đủ metadata để định danh văn bản/)).toBeInTheDocument();
    expect(screen.getByText('Chưa có liên kết chính thức')).toBeInTheDocument();
    expect(screen.getByText('Mã nguồn: chunk-unknown')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Mở nguồn/i })).not.toBeInTheDocument();
  });

  it('defensively separates legacy flattened fields in the excerpt', () => {
    render(
      <SourceDrawer
        documents={[
          {
            page_content: 'Tài liệu đính kèm || 08/2022/NĐ-CP || Điều 77 quy định trách nhiệm tái chế.',
            document_id: 'chunk-77',
            metadata: {
              source_id: 'nd-08-2022',
              Source_Title: 'Nghị định số 08/2022/NĐ-CP',
              Document_Number: '08/2022/NĐ-CP',
              legal_anchor: 'Điều 77',
            },
          },
        ]}
        isOpen
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/Tài liệu đính kèm/)).toBeInTheDocument();
    expect(screen.getByText(/Điều 77 quy định trách nhiệm tái chế/)).toBeInTheDocument();
    expect(screen.queryByText(/\|\|/)).not.toBeInTheDocument();
  });
});
