import { describe, expect, it } from 'vitest';
import { eprPlainName, errorPresentation, previewNotice, safeStopCopy, taskCopy } from './userCopy';

describe('user-facing copy', () => {
  it('keeps default task labels understandable without internal vocabulary', () => {
    const visible = [
      eprPlainName,
      previewNotice,
      ...Object.values(taskCopy).flatMap((copy) => Object.values(copy)),
      ...Object.values(safeStopCopy).flatMap((copy) => Object.values(copy)),
    ].join(' ').toLowerCase();
    for (const internalWord of ['workflow', 'corpus', 'evidence', 'facts', 'pipeline', 'safe stop']) {
      expect(visible).not.toContain(internalWord);
    }
    expect(eprPlainName).toContain('trách nhiệm mở rộng của nhà sản xuất và nhập khẩu');
  });

  it('maps technical error codes to an actionable Vietnamese message', () => {
    expect(errorPresentation({ code: 'rate_limited', message: 'HTTP 429', retryable: true })).toEqual({
      title: 'Bạn đang gửi yêu cầu hơi nhanh',
      message: 'Vui lòng chờ một chút rồi thử lại.',
    });
  });
});
