import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MarkdownRenderer } from './markdown';

describe('MarkdownRenderer citations', () => {
  it('creates safe fragment links for plain markers only', async () => {
    const user = userEvent.setup();
    const onCitationClick = vi.fn();
    render(
      <MarkdownRenderer
        content={'Căn cứ [1]. Mã `const ref = "[2]"`. [Trang có [3]](https://example.com).'}
        onCitationClick={onCitationClick}
      />,
    );

    const citation = screen.getByRole('link', { name: '[1]' });
    expect(citation).toHaveAttribute('href', '#source-1');
    expect(screen.queryByRole('link', { name: '[2]' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Trang có/ })).toHaveAttribute('href', 'https://example.com');
    await user.click(citation);
    expect(onCitationClick).toHaveBeenCalledWith(1);
  });

  it('supports comma-separated citations and renders interactive hover card preview', async () => {
    const user = userEvent.setup();
    const onCitationClick = vi.fn();
    const mockDocuments = [
      {
        page_content: 'Điều 362 quy định về đơn yêu cầu công nhận thuận tình ly hôn.',
        metadata: {
          citation_index: 1,
          Source_Title: 'Bộ luật Tố tụng dân sự 2015',
          Dieu: 'Điều 362',
          effective_status: 'active',
        },
      },
      {
        page_content: 'Điều 81 quy định về việc trông nom, chăm sóc con sau ly hôn.',
        metadata: {
          citation_index: 2,
          Source_Title: 'Luật Hôn nhân và Gia đình 2014',
          Dieu: 'Điều 81',
          effective_status: 'active',
        },
      },
    ];

    render(
      <MarkdownRenderer
        content={'Thủ tục theo [1, 2] quy định rõ.'}
        documents={mockDocuments}
        onCitationClick={onCitationClick}
      />,
    );

    const citation1 = screen.getByRole('link', { name: '[1]' });
    const citation2 = screen.getByRole('link', { name: '[2]' });
    expect(citation1).toHaveAttribute('href', '#source-1');
    expect(citation2).toHaveAttribute('href', '#source-2');

    // Hover over citation 1 to display deer-flow preview card
    await user.hover(citation1);
    await waitFor(() => {
      expect(screen.getByText('Bộ luật Tố tụng dân sự 2015')).toBeInTheDocument();
      expect(screen.getByText('Đang có hiệu lực')).toBeInTheDocument();
    });

    await user.click(citation1);
    expect(onCitationClick).toHaveBeenCalledWith(1);
  });
});
