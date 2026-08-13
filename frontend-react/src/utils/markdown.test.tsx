import { render, screen } from '@testing-library/react';
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
});
