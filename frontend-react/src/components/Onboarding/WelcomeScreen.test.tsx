import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WelcomeScreen } from './WelcomeScreen';

describe('WelcomeScreen quick actions', () => {
  it('prefills the assessment intent without sending a network-backed turn', () => {
    const onSendPrompt = vi.fn();
    const onPrefillPrompt = vi.fn();
    render(
      <WelcomeScreen
        draftText=""
        isStreaming={false}
        onClearIntent={vi.fn()}
        onDraftChange={vi.fn()}
        onPrefillPrompt={onPrefillPrompt}
        onSendPrompt={onSendPrompt}
        onStop={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /kiểm tra nghĩa vụ/i }));

    expect(onPrefillPrompt).toHaveBeenCalledWith(
      'Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?',
      'case_assessment',
    );
    expect(onSendPrompt).not.toHaveBeenCalled();
  });

  it('keeps every action and example as editable prefill and restores composer focus', () => {
    const onSendPrompt = vi.fn();
    const onPrefillPrompt = vi.fn();
    render(
      <WelcomeScreen
        draftText=""
        isStreaming={false}
        onClearIntent={vi.fn()}
        onDraftChange={vi.fn()}
        onPrefillPrompt={onPrefillPrompt}
        onSendPrompt={onSendPrompt}
        onStop={vi.fn()}
      />,
    );

    const actionLabels = ['Tra cứu quy định', 'Kiểm tra nghĩa vụ', 'Lập checklist'];
    for (const label of actionLabels) {
      fireEvent.click(screen.getByRole('button', { name: label }));
    }
    const exampleButtons = screen.getAllByRole('button').filter((button) => button.textContent?.includes('EPR'));
    for (const button of exampleButtons) fireEvent.click(button);

    expect(onPrefillPrompt).toHaveBeenCalledTimes(actionLabels.length + exampleButtons.length);
    expect(onSendPrompt).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Câu hỏi pháp lý' }));
  });
});
