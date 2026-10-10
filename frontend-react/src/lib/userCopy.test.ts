import { describe, expect, it } from 'vitest';
import {
  authFailureCopy,
  authSessionExpiredCopy,
  authSignedOutCopy,
  capabilityUnavailableCopy,
  errorPresentation,
  safeStopCopy,
} from './userCopy';

describe('user-facing copy', () => {
  it('maps technical error codes to an actionable Vietnamese message', () => {
    expect(errorPresentation({ code: 'rate_limited', message: 'HTTP 429', retryable: true })).toEqual({
      title: 'Bạn đang gửi yêu cầu hơi nhanh',
      message: 'Vui lòng chờ một chút rồi thử lại.',
    });
    expect(errorPresentation({ code: 'pipeline_error', message: 'Request failed with status code 500', retryable: true })).toEqual({
      title: 'Không thể hoàn tất câu trả lời',
      message: 'Hãy thử lại hoặc thu hẹp câu hỏi.',
    });
    expect(errorPresentation({ code: 'capacity_exceeded', message: '', retryable: true })).toEqual({
      title: 'Hệ thống đang xử lý nhiều yêu cầu',
      message: 'Vui lòng chờ vài giây rồi thử lại.',
    });
  });

  it('keeps blocked capability reasons understandable', () => {
    expect(capabilityUnavailableCopy('corpus_not_ready')).toContain('dữ liệu pháp luật');
    expect(capabilityUnavailableCopy('provider_not_configured')).not.toContain('provider_not_configured');
    expect(capabilityUnavailableCopy('', true)).toContain('Không thể kết nối');
    expect(Object.values(safeStopCopy).flatMap((copy) => Object.values(copy)).every((text) => text.length > 0)).toBe(true);
  });

  it('keeps authentication failures out of the user-facing copy', () => {
    const rawException = 'invalid_client: oidc token endpoint returned HTTP 401';

    expect(authFailureCopy).toBe('Đăng nhập chưa hoàn tất. Vui lòng thử lại để tiếp tục.');
    expect(authFailureCopy).not.toContain(rawException);
    expect(authSessionExpiredCopy).toContain('Đăng nhập lại');
    expect(authSignedOutCopy).toContain('Đăng nhập');
  });
});
