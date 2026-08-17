import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WelcomeScreen } from './WelcomeScreen';

describe('WelcomeScreen legal goal buttons & dynamic suggestions', () => {
  it('renders the 3 core legal goal buttons', () => {
    render(
      <WelcomeScreen
        draftText=""
        isStreaming={false}
        onClearIntent={vi.fn()}
        onDraftChange={vi.fn()}
        onPrefillPrompt={vi.fn()}
        onSendPrompt={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: /kiểm tra tính hợp pháp & nghĩa vụ/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /hướng dẫn hồ sơ & thủ tục/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /bảo vệ quyền lợi & tranh chấp/i })).toBeInTheDocument();
  });

  it('switches suggestions and placeholder dynamically when a goal button is clicked', () => {
    const onPrefillPrompt = vi.fn();
    render(
      <WelcomeScreen
        draftText=""
        isStreaming={false}
        onClearIntent={vi.fn()}
        onDraftChange={vi.fn()}
        onPrefillPrompt={onPrefillPrompt}
        onSendPrompt={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    // Initially default suggestions
    expect(screen.getByText(/gợi ý tình huống pháp lý phổ biến/i)).toBeInTheDocument();

    // Click Goal 1: Legality
    fireEvent.click(screen.getByRole('button', { name: /kiểm tra tính hợp pháp & nghĩa vụ/i }));
    expect(screen.getByText(/tình huống mẫu: kiểm tra tính hợp pháp & nghĩa vụ/i)).toBeInTheDocument();
    expect(screen.getByText(/phạt vi phạm 15% giá trị/i)).toBeInTheDocument();

    // Click a suggestion from Goal 1
    fireEvent.click(screen.getByText(/phạt vi phạm 15% giá trị/i));
    expect(onPrefillPrompt).toHaveBeenCalledWith(
      expect.stringContaining('15% giá trị'),
      'legal_lookup',
    );

    // Click Goal 3: Dispute
    fireEvent.click(screen.getByRole('button', { name: /bảo vệ quyền lợi & tranh chấp/i }));
    expect(screen.getByText(/tình huống mẫu: bảo vệ quyền lợi & tranh chấp/i)).toBeInTheDocument();
    expect(screen.getByText(/bên bán đổi ý không bán và không chịu trả lại tiền cọc/i)).toBeInTheDocument();

    // Click reset "Xem tất cả chủ đề"
    fireEvent.click(screen.getByRole('button', { name: /xem tất cả chủ đề/i }));
    expect(screen.getByText(/gợi ý tình huống pháp lý phổ biến/i)).toBeInTheDocument();
  });

  it('toggles active goal off when clicked again', () => {
    render(
      <WelcomeScreen
        draftText=""
        isStreaming={false}
        onClearIntent={vi.fn()}
        onDraftChange={vi.fn()}
        onPrefillPrompt={vi.fn()}
        onSendPrompt={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    const goalBtn = screen.getByRole('button', { name: /hướng dẫn hồ sơ & thủ tục/i });
    fireEvent.click(goalBtn);
    expect(screen.getByText(/tình huống mẫu: hướng dẫn hồ sơ & thủ tục/i)).toBeInTheDocument();

    // Click again to toggle off
    fireEvent.click(goalBtn);
    expect(screen.getByText(/gợi ý tình huống pháp lý phổ biến/i)).toBeInTheDocument();
  });

  it('disables goal buttons and inputs when isStreaming or disabled is true', () => {
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
      />,
    );

    expect(screen.getByRole('button', { name: /kiểm tra tính hợp pháp & nghĩa vụ/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /hướng dẫn hồ sơ & thủ tục/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /bảo vệ quyền lợi & tranh chấp/i })).toBeDisabled();
  });
});

