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
});
