import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { submitFeedback } from '@/api/feedback';
import { useChatStore } from '@/state/chatStore';
import type { ChatMessage } from '@/types';
import { MessageActions } from './MessageActions';

vi.mock('@/api/feedback', () => ({ submitFeedback: vi.fn() }));

const submitFeedbackMock = vi.mocked(submitFeedback);

function message(status: ChatMessage['status']): ChatMessage {
  return {
    id: 'assistant-7',
    serverMessageId: 7,
    role: 'assistant',
    content: 'Kết quả',
    timestamp: '2026-08-13T00:00:00Z',
    status,
  };
}

describe('MessageActions', () => {
  beforeEach(() => {
    submitFeedbackMock.mockReset();
    useChatStore.getState().clearChat();
    useChatStore.getState().setActiveSession('conversation-1');
  });

  it('hides feedback and regeneration for stopped messages', () => {
    render(<MessageActions copied={false} message={message('stopped')} onCopy={vi.fn()} onRegenerate={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Câu trả lời hữu ích' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Tạo lại câu trả lời' })).not.toBeInTheDocument();
  });

  it('persists feedback state for a completed durable message', async () => {
    const user = userEvent.setup();
    const completed = message('complete');
    useChatStore.getState().setMessages([completed]);
    submitFeedbackMock.mockResolvedValue({ status: 'ok' });
    render(<MessageActions copied={false} message={completed} onCopy={vi.fn()} onRegenerate={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Câu trả lời hữu ích' }));
    expect(submitFeedbackMock).toHaveBeenCalledWith({ session_id: 'conversation-1', message_id: 7, rating: 2 });
    expect(useChatStore.getState().messages[0].feedbackState).toBe('saved');
    expect(useChatStore.getState().messages[0].feedback?.rating).toBe(2);
  });
});
