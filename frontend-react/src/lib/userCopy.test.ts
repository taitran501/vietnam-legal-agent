import { describe, expect, it } from 'vitest';
import { errorPresentation, taskCopy } from './userCopy';

describe('user-facing copy', () => {
  it('keeps default task labels understandable without internal vocabulary', () => {
    const visible = Object.values(taskCopy).flatMap((copy) => Object.values(copy)).join(' ').toLowerCase();
    expect(visible).not.toContain('workflow');
    expect(visible).not.toContain('corpus');
    expect(visible).not.toContain('evidence');
    expect(visible).not.toContain('facts');
  });

  it('maps technical error codes to an actionable Vietnamese message', () => {
    expect(errorPresentation({ code: 'rate_limited', message: 'HTTP 429', retryable: true })).toEqual({
      title: 'Bạn đang gửi yêu cầu hơi nhanh',
      message: 'Vui lòng chờ một chút rồi thử lại.',
    });
  });
});
