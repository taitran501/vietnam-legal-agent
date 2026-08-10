import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WorkflowResultCard } from './WorkflowResultCard';

describe('WorkflowResultCard', () => {
  it('makes a missing-facts stop visible instead of implying a conclusion', () => {
    render(
      <WorkflowResultCard
        workflow={{
          task_type: 'assess_epr_obligation',
          missing_facts: ['material'],
          termination_reason: 'awaiting_user_input',
        }}
      />
    );

    expect(screen.getByText('Cần thêm thông tin để tiếp tục')).toBeInTheDocument();
    expect(screen.getByText(/vật liệu chính/i)).toBeInTheDocument();
  });

  it('shows a structured checklist without duplicating the source drawer', () => {
    render(
      <WorkflowResultCard
        workflow={{
          checklist: [{ item: 'Đối chiếu Điều 77' }],
          citations: [{ index: 1, label: 'Điều 77' }],
        }}
      />
    );

    expect(screen.getByText('Checklist đề xuất')).toBeInTheDocument();
    expect(screen.getByText('Đối chiếu Điều 77')).toBeInTheDocument();
    expect(screen.queryByText('[1] Điều 77')).not.toBeInTheDocument();
  });

  it('uses a safe-stop state when evidence is insufficient', () => {
    render(<WorkflowResultCard workflow={{ termination_reason: 'insufficient_evidence' }} />);
    expect(screen.getByText('Chưa đủ căn cứ để trả lời chắc chắn')).toBeInTheDocument();
  });
});
