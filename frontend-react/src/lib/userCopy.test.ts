import { describe, expect, it } from 'vitest';
import {
  authFailureCopy,
  authSessionExpiredCopy,
  authSignedOutCopy,
  capabilityUnavailableCopy,
  eprPlainName,
  errorPresentation,
  previewNotice,
  safeStopCopy,
  taskCopy,
} from './userCopy';

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

  it('keeps guided turn prompts aligned with the selected task', () => {
    expect(taskCopy.assess_epr_obligation.turnPrompt).toContain('kiểm tra trường hợp');
    expect(taskCopy.build_compliance_checklist.turnPrompt).toContain('tạo danh sách việc cần làm');
    expect(taskCopy.build_compliance_checklist.turnPrompt).not.toContain('kiểm tra trường hợp');
  });

  it('maps blocked capability reasons to plain Vietnamese copy', () => {
    expect(capabilityUnavailableCopy('corpus_not_ready')).toContain('dữ liệu pháp luật');
    expect(capabilityUnavailableCopy('provider_not_configured')).not.toContain('provider_not_configured');
    expect(capabilityUnavailableCopy('', true)).toContain('Không thể kết nối');
  });

  it('keeps authentication failures out of the user-facing copy', () => {
    const rawException = 'invalid_client: oidc token endpoint returned HTTP 401';

    expect(authFailureCopy).toBe('Đăng nhập chưa hoàn tất. Vui lòng thử lại để tiếp tục.');
    expect(authFailureCopy).not.toContain(rawException);
    expect(authSessionExpiredCopy).toContain('Đăng nhập lại');
    expect(authSignedOutCopy).toContain('Đăng nhập');
  });
});
