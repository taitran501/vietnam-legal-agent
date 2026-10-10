import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { ReasoningBlock } from './ReasoningBlock';
import type { WorkflowStep } from '@/types';

describe('ReasoningBlock (Deer-Flow Chain of Thought)', () => {
  it('renders streaming state with live progress and distinct steps without duplicates', () => {
    const steps: WorkflowStep[] = [
      {
        step: 1,
        action: 'search_legal_provisions',
        label: 'Truy xuất kho văn bản & điều khoản pháp luật',
        status: 'completed',
        latency_ms: 180,
        details: { query: 'đơn phương ly hôn' },
      },
      {
        step: 2,
        action: 'evaluate_legal_case',
        label: 'Áp dụng quy tắc pháp lý & đối chiếu điều kiện',
        status: 'running',
      },
    ];

    render(
      <ReasoningBlock
        isStreaming={true}
        steps={steps}
        statusMessage="Đang đối chiếu quy định pháp luật…"
      />,
    );

    // Header title
    expect(screen.getByText('Tiến trình tra cứu & suy luận pháp lý…')).toBeInTheDocument();

    // Steps
    expect(screen.getByText('Truy xuất kho văn bản & điều khoản pháp luật')).toBeInTheDocument();
    expect(screen.getByText('Kho văn bản đã cấu hình')).toBeInTheDocument();
    expect(screen.getByText('“đơn phương ly hôn”')).toBeInTheDocument();
    expect(screen.getByText('180ms')).toBeInTheDocument();

    // Active step running
    expect(screen.getByText('Áp dụng quy tắc pháp lý & đối chiếu điều kiện')).toBeInTheDocument();
    expect(screen.getByText('Đang thực thi…')).toBeInTheDocument();
  });

  it('can be toggled collapsed and expanded', async () => {
    const user = userEvent.setup();
    const steps: WorkflowStep[] = [
      {
        step: 1,
        action: 'verify_citations',
        label: 'Thẩm định phản biện & rà soát hiệu lực văn bản',
        status: 'completed',
        latency_ms: 250,
      },
    ];

    render(
      <ReasoningBlock
        isStreaming={false}
        steps={steps}
        defaultExpanded={false}
      />,
    );

    expect(screen.getByText('Đã đối chiếu & suy luận qua 1 bước')).toBeInTheDocument();
    expect(screen.getByText('Chi tiết')).toBeInTheDocument();

    // Click to expand
    await user.click(screen.getByRole('button', { name: /Đã đối chiếu/i }));
    expect(screen.getByText('Thu gọn')).toBeInTheDocument();
    expect(screen.getByText('Thẩm định phản biện & rà soát hiệu lực văn bản')).toBeInTheDocument();
    expect(screen.getByText('Rà soát hiệu lực VBPL')).toBeInTheDocument();
  });
});
