import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WelcomeScreen } from './WelcomeScreen';

function renderWelcome(
  overrides: {
    disabled?: boolean;
    caseDisabled?: boolean;
    draftText?: string;
  } = {},
) {
  const onSelectIntent = vi.fn();
  render(<WelcomeScreen draftText="" isStreaming={false} onClearIntent={vi.fn()} onDraftChange={vi.fn()} onSelectIntent={onSelectIntent} onSendPrompt={vi.fn()} onStop={vi.fn()} {...overrides} />);
  return { onSelectIntent };
}

describe('WelcomeScreen task categories', () => {
  it('shows exactly three categories and no sample-question section', () => {
    renderWelcome();

    const categories = screen.getByRole('group', { name: 'Mục tiêu pháp lý' });
    expect(within(categories).getAllByRole('button')).toHaveLength(3);
    expect(screen.getByRole('button', { name: 'Tra cứu quy định pháp luật' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tư vấn tình huống' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hồ sơ & thủ tục' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /câu hỏi mẫu/i })).not.toBeInTheDocument();
  });

  it('sets an intent without inserting a sample question and toggles it off', () => {
    const { onSelectIntent } = renderWelcome();
    const input = screen.getByLabelText('Câu hỏi pháp lý');

    fireEvent.click(screen.getByRole('button', { name: 'Tư vấn tình huống' }));
    expect(onSelectIntent).toHaveBeenLastCalledWith('case_assessment');
    expect(input).toHaveValue('');
    expect(input).toHaveAttribute('placeholder', 'Mô tả ngắn gọn tình huống pháp lý…');

    fireEvent.click(screen.getByRole('button', { name: 'Tư vấn tình huống' }));
    expect(onSelectIntent).toHaveBeenLastCalledWith('auto');
    expect(input).toHaveValue('');
  });

  it('preserves a draft when changing its task category', () => {
    const draftText = 'Điều 77 Nghị định 08 quy định gì?';
    const { onSelectIntent } = renderWelcome({ draftText });
    const input = screen.getByLabelText('Câu hỏi pháp lý');

    fireEvent.click(screen.getByRole('button', { name: 'Tra cứu quy định pháp luật' }));
    expect(onSelectIntent).toHaveBeenCalledWith('legal_lookup');
    expect(input).toHaveValue(draftText);
  });

  it('disables only the case-related categories when the workflow is unavailable', () => {
    renderWelcome({ caseDisabled: true });
    const categories = screen.getByRole('group', { name: 'Mục tiêu pháp lý' });

    expect(within(categories).getAllByRole('button')).toHaveLength(3);
    expect(screen.getByRole('button', { name: 'Tra cứu quy định pháp luật' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Tư vấn tình huống' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Hồ sơ & thủ tục' })).toBeDisabled();
  });
});
