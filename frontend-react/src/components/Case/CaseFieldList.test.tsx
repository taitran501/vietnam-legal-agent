import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CaseFieldList } from './CaseFieldList';

describe('CaseFieldList', () => {
  it('renders backend order, help text and field-level errors without owning persistence', () => {
    render(
      <CaseFieldList
        fields={[
          { key: 'market_placement', label: 'market_placement', kind: 'select', options: [{ value: 'vietnam_market', label: 'Đưa ra thị trường Việt Nam' }], required: true, importance: 'required', missing: true, value: '', display_order: 2, help_text: 'Chọn thị trường.' },
          { key: 'business_role', label: 'Vai trò doanh nghiệp', kind: 'select', options: [], required: true, importance: 'required', missing: false, value: '', display_order: 1, help_text: 'Chọn vai trò.' },
        ]}
        validationErrors={{ market_placement: 'Hãy chọn phạm vi hoạt động.' }}
        values={{}}
      />,
    );

    const fields = screen.getAllByRole('combobox');
    expect(fields[0]).toHaveAccessibleName('Vai trò doanh nghiệp');
    expect(fields[1]).toHaveAccessibleName('Phạm vi đưa ra thị trường');
    expect(screen.getByText('Hãy chọn phạm vi hoạt động.')).toBeInTheDocument();
    expect(screen.getByText('Chọn thị trường.')).toBeInTheDocument();
  });
});
