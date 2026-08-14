import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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
    expect(screen.getByText(/vật liệu hoặc quy cách/i)).toBeInTheDocument();
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

    expect(screen.getByText('Danh sách việc cần làm')).toBeInTheDocument();
    expect(screen.getByText('Đối chiếu Điều 77')).toBeInTheDocument();
    expect(screen.queryByText('[1] Điều 77')).not.toBeInTheDocument();
  });

  it('focuses the first cited source from a checklist action', () => {
    const onOpenSources = vi.fn();
    render(
      <WorkflowResultCard
        onOpenSources={onOpenSources}
        workflow={{
          checklist: [{ item: 'Đối chiếu Điều 77', evidence_indices: [2, 4] }],
        }}
      />,
    );

    screen.getByRole('button', { name: 'Xem căn cứ (2, 4)' }).click();
    expect(onOpenSources).toHaveBeenCalledWith(2);
  });

  it('uses a safe-stop state when evidence is insufficient', () => {
    render(<WorkflowResultCard workflow={{ termination_reason: 'insufficient_evidence' }} />);
    expect(screen.getByText('Chưa đủ căn cứ để trả lời chắc chắn')).toBeInTheDocument();
  });

  it('renders an assessment only for a completed decision', () => {
    render(
      <WorkflowResultCard
        workflow={{
          outcome: 'completed',
          result_type: 'assessment',
          assessment: { status: 'likely_in_scope' },
          citations: [{ index: 1, label: 'Điều 77' }],
        }}
      />,
    );
    expect(screen.getByText('Đánh giá sơ bộ')).toBeInTheDocument();
  });

  it('does not present a conclusion while the agent is waiting for facts', () => {
    render(
      <WorkflowResultCard
        workflow={{ outcome: 'needs_information', result_type: 'none', missing_facts: ['market_placement'], assessment: { status: 'needs_information' } }}
      />,
    );
    expect(screen.getByText('Cần thêm thông tin để tiếp tục')).toBeInTheDocument();
    expect(screen.queryByText('Đánh giá sơ bộ')).not.toBeInTheDocument();
  });

  it('exposes the explicit research action for an evidence safe-stop', async () => {
    const onResearch = vi.fn();
    render(
      <WorkflowResultCard
        onResearch={onResearch}
        webResearchReady
        workflow={{ outcome: 'insufficient_evidence', result_type: 'none', termination_reason: 'insufficient_evidence', available_actions: ['research_web'] }}
      />,
    );
    expect(screen.getByRole('button', { name: 'Tìm nguồn công khai' })).toBeInTheDocument();
    screen.getByRole('button', { name: 'Tìm nguồn công khai' }).click();
    expect(onResearch).toHaveBeenCalledOnce();
  });

  it('hides web research when the capability is not ready', () => {
    render(
      <WorkflowResultCard
        onResearch={vi.fn()}
        workflow={{ outcome: 'insufficient_evidence', result_type: 'none', termination_reason: 'insufficient_evidence', available_actions: ['research_web'] }}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Tìm nguồn công khai' })).not.toBeInTheDocument();
  });

  it('does not show an unconfirmed update date when no date is provided', () => {
    render(<WorkflowResultCard workflow={{ termination_reason: 'insufficient_evidence' }} />);
    expect(screen.queryByText(/Thông tin được cập nhật đến/)).not.toBeInTheDocument();
  });

  it('offers a preliminary report only for completed structured results', () => {
    const onExport = vi.fn();
    render(
      <WorkflowResultCard
        onExport={onExport}
        workflow={{
          outcome: 'completed',
          result_type: 'assessment',
          assessment: { status: 'likely_in_scope', conclusion: 'Có khả năng thuộc phạm vi EPR' },
        }}
      />,
    );

    screen.getByRole('button', { name: 'Tải báo cáo sơ bộ' }).click();
    expect(onExport).toHaveBeenCalledOnce();
  });
});
