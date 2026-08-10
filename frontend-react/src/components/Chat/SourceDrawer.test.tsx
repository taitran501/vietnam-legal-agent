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
            metadata: { Dieu: 'Điều 77', source: 'Nghị định 08/2022/NĐ-CP' },
          },
        ]}
        isOpen
        onClose={onClose}
      />
    );

    expect(screen.getByRole('dialog', { name: 'Nguồn tham khảo' })).toBeInTheDocument();
    expect(screen.getByText('Nghị định 08/2022/NĐ-CP')).toBeInTheDocument();
    expect(screen.getByText(/Điều 77/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Đóng' }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
