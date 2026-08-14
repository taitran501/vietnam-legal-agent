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
    expect(screen.getByRole('link', { name: 'Mở nguồn' })).toHaveAttribute('href', 'https://vanban.chinhphu.vn/?docid=205092&pageid=27160');
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
});
