import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { resolveCaseForm } from '@/api/caseForm';
import { GuidedCaseCard } from './GuidedCaseCard';

vi.mock('@/api/caseForm', () => ({
  resolveCaseForm: vi.fn(async (_taskType: string, updates: Record<string, { value: string }>) => ({
    form_version: 'case-form-v1',
    task_type: 'assess_epr_obligation',
    status: updates.business_role?.value && updates.object_kind?.value ? 'ready' : 'collecting',
    facts: Object.fromEntries(Object.entries(updates).map(([key, item]) => [key, { value: item.value, source: 'case_panel', confirmation_status: 'user_confirmed' }])),
    fields: [
      { key: 'business_role', label: 'Vai trò doanh nghiệp', kind: 'select', options: [{ value: 'manufacturer', label: 'Nhà sản xuất' }], required: true, importance: 'required', missing: !updates.business_role?.value, value: updates.business_role?.value || '', help_text: 'Chọn vai trò.' },
      { key: 'object_kind', label: 'Loại đối tượng', kind: 'select', options: [{ value: 'product', label: 'Sản phẩm' }], required: true, importance: 'required', missing: !updates.object_kind?.value, value: updates.object_kind?.value || '', help_text: 'Chọn đối tượng.' },
    ],
    missing_facts: ['business_role', 'object_kind'].filter((key) => !updates[key]?.value),
    validation_errors: {},
    completed_count: Object.values(updates).filter((item) => item.value).length,
    required_count: 2,
  })),
}));

describe('GuidedCaseCard', () => {
  it('resolves while editing and submits one completed draft', async () => {
    const onSubmit = vi.fn(async () => undefined);
    render(<GuidedCaseCard onSubmit={onSubmit} taskType="assess_epr_obligation" />);

    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Vai trò doanh nghiệp' })).toBeInTheDocument());
    fireEvent.change(screen.getByRole('combobox', { name: 'Vai trò doanh nghiệp' }), { target: { value: 'manufacturer' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Loại đối tượng' }), { target: { value: 'product' } });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Kiểm tra trường hợp' })).toBeEnabled(), { timeout: 1500 });
    fireEvent.click(screen.getByRole('button', { name: 'Kiểm tra trường hợp' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(
      { business_role: 'manufacturer', object_kind: 'product' },
      { business_role: 'user_confirmed', object_kind: 'user_confirmed' },
      'assess_epr_obligation',
    ));
  });

  it('keeps the draft visible when the submit handler fails', async () => {
    const onSubmit = vi.fn(async () => {
      throw new Error('Dịch vụ tạm thời không khả dụng.');
    });
    render(<GuidedCaseCard onSubmit={onSubmit} taskType="assess_epr_obligation" />);

    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Vai trò doanh nghiệp' })).toBeInTheDocument());
    fireEvent.change(screen.getByRole('combobox', { name: 'Vai trò doanh nghiệp' }), { target: { value: 'manufacturer' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Loại đối tượng' }), { target: { value: 'product' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Kiểm tra trường hợp' })).toBeEnabled(), { timeout: 1500 });

    fireEvent.click(screen.getByRole('button', { name: 'Kiểm tra trường hợp' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Dịch vụ tạm thời không khả dụng.'));
    expect(screen.getByRole('combobox', { name: 'Vai trò doanh nghiệp' })).toHaveValue('manufacturer');
  });

  it('hides transport details and offers a retry when resolving the form fails', async () => {
    vi.mocked(resolveCaseForm).mockRejectedValueOnce(new Error('Request failed with status code 500'));
    const initialState = {
      form_version: 'case-form-v1',
      task_type: 'assess_epr_obligation' as const,
      status: 'collecting' as const,
      facts: {},
      fields: [
        { key: 'business_role', label: 'Vai trò doanh nghiệp', kind: 'select' as const, options: [{ value: 'manufacturer', label: 'Nhà sản xuất' }], required: true, importance: 'required' as const, missing: true, value: '', help_text: 'Chọn vai trò.' },
      ],
      missing_facts: ['business_role'],
      validation_errors: {},
      completed_count: 0,
      required_count: 1,
    };
    render(<GuidedCaseCard initialCaseState={initialState} onSubmit={vi.fn(async () => undefined)} taskType="assess_epr_obligation" />);

    fireEvent.change(screen.getByRole('combobox', { name: 'Vai trò doanh nghiệp' }), { target: { value: 'manufacturer' } });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Thông tin bạn đã nhập vẫn được giữ lại'));
    expect(screen.getByRole('alert')).not.toHaveTextContent('Request failed with status code 500');
    fireEvent.click(screen.getByRole('button', { name: 'Thử cập nhật biểu mẫu' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });
});
