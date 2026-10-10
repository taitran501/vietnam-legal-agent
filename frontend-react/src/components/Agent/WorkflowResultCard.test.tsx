import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WorkflowResultCard } from './WorkflowResultCard';

describe('WorkflowResultCard', () => {
  it('shows a structured checklist without duplicating the source drawer', () => {
    render(
      <WorkflowResultCard
        workflow={{
          checklist: [{ item: 'Đối chiếu Điều 36 Bộ luật Lao động' }],
          citations: [{ index: 1, label: 'Điều 36 Bộ luật Lao động' }],
        }}
      />
    );

    expect(screen.getByText('Danh sách việc cần làm')).toBeInTheDocument();
    expect(screen.getByText('Đối chiếu Điều 36 Bộ luật Lao động')).toBeInTheDocument();
    expect(screen.queryByText('[1] Điều 36 Bộ luật Lao động')).not.toBeInTheDocument();
  });

  it('focuses the first cited source from a checklist action', () => {
    const onOpenSources = vi.fn();
    render(
      <WorkflowResultCard
        onOpenSources={onOpenSources}
        workflow={{
          checklist: [{ item: 'Đối chiếu Điều 36 Bộ luật Lao động', evidence_indices: [2, 4] }],
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

  it('explains when an article was found but its current status is unverified', () => {
    render(
      <WorkflowResultCard
        workflow={{
          safe_stop_reason: 'current_law_status_unverified',
          available_actions: ['research_web'],
        }}
        onResearch={vi.fn()}
        webResearchReady
      />,
    );

    expect(screen.getByText('Chưa xác minh được hiệu lực hiện hành')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tìm nguồn công khai' })).toBeInTheDocument();
  });

  it('renders an assessment only for a completed decision', () => {
    render(
      <WorkflowResultCard
        workflow={{
          outcome: 'completed',
          result_type: 'assessment',
          assessment: { status: 'likely_in_scope' },
          citations: [{ index: 1, label: 'Điều 36 Bộ luật Lao động' }],
        }}
      />,
    );
    expect(screen.getByText('Đánh giá sơ bộ')).toBeInTheDocument();
  });

  it('does not present a conclusion while the agent is waiting for facts', () => {
    render(
      <WorkflowResultCard
        workflow={{ outcome: 'needs_information', result_type: 'none', assessment: { status: 'needs_information' } }}
      />,
    );
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
          assessment: { status: 'likely_in_scope', conclusion: 'Có căn cứ ban đầu cho đánh giá' },
        }}
      />,
    );

    screen.getByRole('button', { name: 'Tải báo cáo sơ bộ' }).click();
    expect(onExport).toHaveBeenCalledOnce();
  });
});
