import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ChatMessageComponent } from './ChatMessage';

describe('ChatMessageComponent', () => {
  it('uses a safe source label for an unknown response source', () => {
    render(
      <ChatMessageComponent
        message={{
          id: 'assistant-1',
          role: 'assistant',
          content: 'Câu trả lời',
          timestamp: '2026-08-14T00:00:00Z',
          source: 'future_internal_source' as never,
          workflow: { preview: true },
        }}
        onOpenSources={vi.fn()}
        webResearchReady={false}
      />,
    );

    expect(screen.getByText('Nguồn tham khảo')).toBeInTheDocument();
    expect(screen.queryByText('future_internal_source')).not.toBeInTheDocument();
    expect(screen.queryByText(/Bản thử nghiệm:/)).not.toBeInTheDocument();
  });
});
