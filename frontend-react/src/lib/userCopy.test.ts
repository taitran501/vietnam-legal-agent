import { describe, expect, it } from 'vitest';
import { capabilityUnavailableCopy, caseFormErrorMessage, eprPlainName, errorPresentation, previewNotice, safeStopCopy, taskCopy } from './userCopy';

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
    expect(errorPresentation({ code: 'pipeline_error', message: 'Request failed with status code 500', retryable: true })).toEqual({
      title: 'Không thể hoàn tất câu trả lời',
      message: 'Hãy thử lại hoặc thu hẹp câu hỏi.',
    });
    expect(errorPresentation({ code: 'capacity_exceeded', message: '', retryable: true })).toEqual({
      title: 'Hệ thống đang xử lý nhiều yêu cầu',
      message: 'Vui lòng chờ vài giây rồi thử lại.',
    });
  });

  it('does not expose transport errors beside the guided form', () => {
    expect(caseFormErrorMessage(new Error('Request failed with status code 500'))).toContain('Thông tin bạn đã nhập vẫn được giữ lại');
    expect(caseFormErrorMessage({ response: { status: 422 } })).toContain('chưa hợp lệ');
    expect(caseFormErrorMessage(new Error('Dịch vụ tạm thời không khả dụng.'))).toBe('Dịch vụ tạm thời không khả dụng.');
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
});
