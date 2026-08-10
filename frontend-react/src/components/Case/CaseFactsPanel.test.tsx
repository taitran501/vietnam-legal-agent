import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { updateCaseState } from '@/api/sessions';
import type { CaseState } from '@/types';
import { CaseFactsPanel } from './CaseFactsPanel';

vi.mock('@/api/sessions', () => ({
  updateCaseState: vi.fn(),
}));

const updateCaseStateMock = vi.mocked(updateCaseState);

function caseState(overrides: Partial<CaseState> = {}): CaseState {
  return {
    task_type: 'assess_epr_obligation',
    status: 'collecting',
    schema_version: 'v4',
    facts: { business_role: 'manufacturer' },
    missing_facts: ['market_placement'],
    fields: [
      {
        key: 'business_role',
        label: 'Vai trò doanh nghiệp',
        kind: 'select',
        options: [{ value: 'manufacturer', label: 'Nhà sản xuất' }],
        required: true,
        missing: false,
        value: 'manufacturer',
      },
      {
        key: 'market_placement',
        label: 'Phạm vi đưa ra thị trường',
        kind: 'select',
        options: [{ value: 'vietnam_market', label: 'Đưa ra thị trường Việt Nam' }],
        required: true,
        missing: true,
        value: '',
      },
    ],
    ...overrides,
  };
}

describe('CaseFactsPanel', () => {
  beforeEach(() => {
    updateCaseStateMock.mockReset();
  });

  it('renders backend-defined fields, saves a patch, and does not continue implicitly', async () => {
    const user = userEvent.setup();
    const onCaseChange = vi.fn();
    const onContinue = vi.fn();
    const next = caseState({ facts: { business_role: 'manufacturer', market_placement: 'vietnam_market' }, missing_facts: [], status: 'ready' });
    updateCaseStateMock.mockResolvedValue(next);
    render(<CaseFactsPanel conversationId="case-1" caseState={caseState()} onCaseChange={onCaseChange} onContinue={onContinue} />);

    expect(screen.getByText('cần bổ sung')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/Phạm vi đưa ra thị trường/), 'vietnam_market');
    await user.click(screen.getByRole('button', { name: 'Lưu thông tin trường hợp' }));

    expect(updateCaseStateMock).toHaveBeenCalledWith(
      'case-1',
      { business_role: 'manufacturer', market_placement: 'vietnam_market' },
      'assess_epr_obligation',
    );
    expect(onCaseChange).toHaveBeenCalledWith(next);
    expect(onContinue).not.toHaveBeenCalled();
  });

  it('only continues after the backend case has no missing facts', async () => {
    const user = userEvent.setup();
    const onContinue = vi.fn();
    render(
      <CaseFactsPanel
        conversationId="case-2"
        caseState={caseState({
          status: 'ready',
          facts: { business_role: 'manufacturer', market_placement: 'vietnam_market' },
          missing_facts: [],
          fields: caseState().fields?.map((field) => ({ ...field, missing: false, value: field.key === 'market_placement' ? 'vietnam_market' : field.value })),
        })}
        onCaseChange={vi.fn()}
        onContinue={onContinue}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Tiếp tục đánh giá' }));
    expect(onContinue).toHaveBeenCalledWith({ business_role: 'manufacturer', market_placement: 'vietnam_market' });
  });

  it('keeps persisted keys out of the visible case panel when field metadata is absent', () => {
    render(
      <CaseFactsPanel
        conversationId="case-3"
        caseState={caseState({
          fields: undefined,
          facts: {
            business_role: 'manufacturer',
            object_kind: 'commercial_packaging',
            material: 'plastic',
          },
          missing_facts: [],
          status: 'ready',
        })}
        onCaseChange={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    expect(screen.getByText('Thông tin đã xác nhận')).toBeInTheDocument();
    expect(screen.getByLabelText('Vai trò doanh nghiệp')).toHaveValue('manufacturer');
    expect(screen.getByLabelText('Loại đối tượng')).toHaveValue('commercial_packaging');
    expect(screen.getByLabelText('Vật liệu hoặc quy cách')).toHaveValue('plastic');
    expect(screen.queryByText('business_role')).not.toBeInTheDocument();
    expect(screen.queryByText('commercial_packaging')).not.toBeInTheDocument();
  });
});
