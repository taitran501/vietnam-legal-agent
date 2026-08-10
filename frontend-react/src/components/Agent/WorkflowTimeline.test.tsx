import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { WorkflowTimeline } from './WorkflowTimeline';

describe('WorkflowTimeline', () => {
  it('keeps the current action compact and reveals the bounded action history on demand', async () => {
    const user = userEvent.setup();
    render(
      <WorkflowTimeline
        isStreaming
        steps={[
          { step: 1, action: 'understand_task', status: 'completed' },
          { step: 2, action: 'retrieve_legal', status: 'completed' },
        ]}
      />
    );

    expect(screen.getByText('Tìm văn bản liên quan')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Tìm văn bản liên quan/i }));
    expect(screen.getByText('Hiểu yêu cầu')).toBeInTheDocument();
  });

  it('shows the meaningful phase summary after a fast safe stop', () => {
    render(
      <WorkflowTimeline
        isStreaming={false}
        steps={[
          { step: 1, action: 'understand', label: 'Hiểu yêu cầu', status: 'completed' },
          { step: 2, action: 'collect_information', label: 'Thu thập thông tin · còn thiếu 3 thông tin', status: 'completed' },
        ]}
      />,
    );

    expect(screen.getByText(/Đã hoàn tất 2 bước · Thu thập thông tin · còn thiếu 3 thông tin/)).toBeInTheDocument();
  });
});
