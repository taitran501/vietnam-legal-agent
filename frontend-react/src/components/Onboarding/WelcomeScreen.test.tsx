import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WelcomeScreen } from './WelcomeScreen';

describe('WelcomeScreen quick actions', () => {
  it('opens the guided assessment without sending a network-backed turn', () => {
    const onSendPrompt = vi.fn();
    const onPrefillPrompt = vi.fn();
    const onStartCase = vi.fn();
    render(
      <WelcomeScreen
        draftText=""
        isStreaming={false}
        onClearIntent={vi.fn()}
        onDraftChange={vi.fn()}
        onPrefillPrompt={onPrefillPrompt}
        onSendPrompt={onSendPrompt}
        onStop={vi.fn()}
        onStartCase={onStartCase}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /kiểm tra trường hợp của doanh nghiệp/i }));

    expect(onStartCase).toHaveBeenCalledWith('assess_epr_obligation');
    expect(onPrefillPrompt).not.toHaveBeenCalled();
    expect(onSendPrompt).not.toHaveBeenCalled();
  });

  it('keeps legal lookup and examples as editable prefill', () => {
    const onSendPrompt = vi.fn();
    const onPrefillPrompt = vi.fn();
    const onStartCase = vi.fn();
    render(
      <WelcomeScreen
        draftText=""
        isStreaming={false}
        onClearIntent={vi.fn()}
        onDraftChange={vi.fn()}
        onPrefillPrompt={onPrefillPrompt}
        onSendPrompt={onSendPrompt}
        onStop={vi.fn()}
        onStartCase={onStartCase}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Tra cứu quy định' }));
    fireEvent.click(screen.getByRole('button', { name: 'Kiểm tra trường hợp của doanh nghiệp' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tạo danh sách việc cần làm' }));
    const exampleButtons = screen.getAllByRole('button').filter((button) => button.textContent?.includes('EPR'));
    for (const button of exampleButtons) fireEvent.click(button);

    expect(onPrefillPrompt).toHaveBeenCalledTimes(1 + exampleButtons.length);
    expect(onStartCase).toHaveBeenCalledTimes(2);
    expect(onSendPrompt).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Câu hỏi pháp lý' }));
  });

  it('keeps a ready case action available when only legal lookup is blocked', () => {
    const onStartCase = vi.fn();
    render(
      <WelcomeScreen
        disabled
        draftText=""
        isStreaming={false}
        onClearIntent={vi.fn()}
        onDraftChange={vi.fn()}
        onPrefillPrompt={vi.fn()}
        onSendPrompt={vi.fn()}
        onStop={vi.fn()}
        onStartCase={onStartCase}
        caseDisabled={false}
      />,
    );

    expect(screen.getByRole('button', { name: 'Tra cứu quy định' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Kiểm tra trường hợp của doanh nghiệp' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Kiểm tra trường hợp của doanh nghiệp' }));
    expect(onStartCase).toHaveBeenCalledWith('assess_epr_obligation');
  });
});
