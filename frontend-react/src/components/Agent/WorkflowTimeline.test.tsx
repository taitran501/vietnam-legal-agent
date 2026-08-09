import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WorkflowTimeline } from './WorkflowTimeline';

describe('WorkflowTimeline', () => {
  it('renders bounded workflow actions with Vietnamese labels', () => {
    render(
      <WorkflowTimeline
        isStreaming={false}
        steps={[
          { step: 1, action: 'understand_task', status: 'completed' },
          { step: 2, action: 'retrieve_legal', status: 'completed' },
        ]}
      />
    );

    expect(screen.getByText('Xác định yêu cầu')).toBeInTheDocument();
    expect(screen.getByText('Tra cứu văn bản pháp luật')).toBeInTheDocument();
  });
});
