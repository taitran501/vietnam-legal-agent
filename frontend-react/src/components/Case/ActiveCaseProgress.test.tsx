import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ActiveCaseProgress } from './ActiveCaseProgress';
import type { CaseState } from '@/types';

describe('ActiveCaseProgress', () => {
  const collectingCase: CaseState = {
    task_type: 'assess_epr_obligation',
    status: 'collecting',
    facts: {
      business_role: 'manufacturer',
      material: 'plastic',
    },
    missing_facts: ['market_placement'],
    completed_count: 2,
    required_count: 3,
  };

  it('renders supplied facts and missing facts properly', () => {
    const onOpenCase = vi.fn();
    render(<ActiveCaseProgress caseState={collectingCase} onOpenCase={onOpenCase} />);

    expect(screen.getByRole('complementary', { name: 'Tiến độ dữ kiện vụ việc' })).toBeInTheDocument();
    expect(screen.getByText(/Đang thu thập \(1 mục cần thêm\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Dữ kiện đã ghi nhận:/i)).toBeInTheDocument();
    expect(screen.getByText(/vai trò doanh nghiệp/i)).toBeInTheDocument();
    expect(screen.getByText(/Dữ kiện đang chờ bổ sung:/i)).toBeInTheDocument();
    expect(screen.getByText(/phạm vi đưa ra thị trường/i)).toBeInTheDocument();

    // Test clicking open full editor
    fireEvent.click(screen.getByRole('button', { name: /Mở bảng chi tiết/i }));
    expect(onOpenCase).toHaveBeenCalledOnce();
  });

  it('supports toggling collapse and expand', () => {
    render(<ActiveCaseProgress caseState={collectingCase} />);

    expect(screen.getByText(/Dữ kiện đã ghi nhận:/i)).toBeInTheDocument();

    // Click collapse
    fireEvent.click(screen.getByRole('button', { name: /Thu gọn/i }));
    expect(screen.queryByText(/Dữ kiện đã ghi nhận:/i)).not.toBeInTheDocument();

    // Click expand
    fireEvent.click(screen.getByRole('button', { name: /Xem chi tiết/i }));
    expect(screen.getByText(/Dữ kiện đã ghi nhận:/i)).toBeInTheDocument();
  });

  it('renders ready state when all facts are gathered', () => {
    const readyCase: CaseState = {
      task_type: 'build_compliance_checklist',
      status: 'ready',
      facts: {
        activity_scope: 'commercial',
      },
      missing_facts: [],
      completed_count: 1,
      required_count: 1,
    };

    render(<ActiveCaseProgress caseState={readyCase} />);

    expect(screen.getByText(/Đã đủ dữ kiện/i)).toBeInTheDocument();
    expect(screen.queryByText(/Dữ kiện đang chờ bổ sung:/i)).not.toBeInTheDocument();
  });
});
