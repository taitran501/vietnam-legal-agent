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

  it('uses the backend label and never exposes an internal action name', async () => {
    const user = userEvent.setup();
    render(
      <WorkflowTimeline
        isStreaming
        steps={[{ step: 1, action: 'internal_private_action', label: 'Đối chiếu nguồn chính thức', status: 'completed' }]}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Đối chiếu nguồn chính thức/i }));
    expect(screen.getAllByText('Đối chiếu nguồn chính thức').length).toBeGreaterThan(0);
    expect(screen.queryByText('internal_private_action')).not.toBeInTheDocument();
  });

  it('labels an interrupted workflow as stopped, not completed', () => {
    render(
      <WorkflowTimeline
        isStreaming={false}
        steps={[{ step: 1, action: 'understand', label: 'Hiểu yêu cầu', status: 'completed' }]}
        turnStatus="stopped"
      />,
    );
    expect(screen.getByText(/Đã dừng theo yêu cầu/)).toBeInTheDocument();
    expect(screen.queryByText(/Đã hoàn tất 1 bước/)).not.toBeInTheDocument();
  });
});
