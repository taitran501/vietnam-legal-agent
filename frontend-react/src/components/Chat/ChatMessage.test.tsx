import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ChatMessageComponent } from './ChatMessage';

describe('ChatMessageComponent', () => {
  it('renders content cleanly without leaking internal source keys', () => {
    render(
      <ChatMessageComponent
        message={{
          id: 'assistant-1',
          role: 'assistant',
          content: 'Câu trả lời',
          timestamp: '2026-08-14T00:00:00Z',
          source: 'legal',
          workflow: { preview: true },
        }}
        onOpenSources={vi.fn()}
        webResearchReady={false}
      />,
    );

    expect(screen.getByText('Câu trả lời')).toBeInTheDocument();
    expect(screen.queryByText('future_internal_source')).not.toBeInTheDocument();
    expect(screen.queryByText(/Bản thử nghiệm:/)).not.toBeInTheDocument();
  });
});
