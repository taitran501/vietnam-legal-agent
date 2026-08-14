import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ErrorBoundary from './ErrorBoundary';

function BrokenChild(): never {
  throw new Error('internal database connection string');
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
  });

  it('shows plain recovery guidance without exposing the raw exception', () => {
    render(
      <ErrorBoundary>
        <BrokenChild />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Ứng dụng vừa gặp lỗi ngoài dự kiến.')).toBeInTheDocument();
    expect(screen.getByText('Hãy thử tải lại trang. Nếu lỗi tiếp tục, hãy báo quản trị viên.')).toBeInTheDocument();
    expect(screen.queryByText('internal database connection string')).not.toBeInTheDocument();
  });
});
