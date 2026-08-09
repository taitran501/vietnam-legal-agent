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

    expect(screen.getByText('Cần bổ sung thông tin')).toBeInTheDocument();
  });

  it('shows citations for a completed compliance output', () => {
    render(
      <WorkflowResultCard
        workflow={{
          checklist: [{ item: 'Đối chiếu Điều 77' }],
          citations: [{ index: 1, label: 'Điều 77' }],
        }}
      />
    );

    expect(screen.getByText('Checklist tuân thủ')).toBeInTheDocument();
    expect(screen.getByText('[1] Điều 77')).toBeInTheDocument();
  });
});
