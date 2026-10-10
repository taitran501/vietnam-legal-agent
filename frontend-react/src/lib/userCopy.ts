import type { StreamError } from '@/types';

export const authSignedOutCopy = 'Đăng nhập để tra cứu pháp luật và lưu lại các cuộc trò chuyện.';
export const authSessionExpiredCopy = 'Phiên đăng nhập đã hết hạn. Đăng nhập lại để tiếp tục tại cuộc trò chuyện này. Vị trí cuộc trò chuyện sẽ được giữ nguyên.';
export const authFailureCopy = 'Đăng nhập chưa hoàn tất. Vui lòng thử lại để tiếp tục.';

export function capabilityUnavailableCopy(reason = '', offline = false): string {
  if (offline) return 'Không thể kết nối tới máy chủ. Bạn có thể thử lại sau ít phút.';
  const messages: Record<string, string> = {
    database_schema_mismatch: 'Chức năng này đang tạm khóa vì lịch sử chưa sẵn sàng. Hãy thử lại sau ít phút.',
    corpus_promotion_blocked: 'Chức năng này đang tạm khóa vì dữ liệu pháp luật chưa sẵn sàng.',
    corpus_not_ready: 'Chức năng này đang tạm khóa vì dữ liệu pháp luật đang được kiểm tra.',
    qdrant_unavailable: 'Chức năng này đang tạm khóa vì kho tìm kiếm pháp luật tạm thời không khả dụng.',
    provider_not_configured: 'Nguồn bổ sung hiện chưa được cấu hình. Bạn vẫn có thể dùng các chức năng khác.',
    dependency_unavailable: 'Một dịch vụ cần thiết đang tạm thời không khả dụng. Hãy thử lại sau ít phút.',
    service_unavailable: 'Dịch vụ này đang tạm thời không khả dụng. Hãy thử lại sau ít phút.',
  };
  return messages[reason] || 'Chức năng này hiện chưa sẵn sàng. Hãy thử lại sau ít phút.';
}

export const safeStopCopy: Record<string, { title: string; message: string }> = {
  out_of_scope: { title: 'Ngoài phạm vi hỗ trợ', message: 'Yêu cầu này không thuộc phạm vi pháp luật mà trợ lý đang hỗ trợ.' },
  insufficient_evidence: { title: 'Chưa đủ căn cứ để trả lời chắc chắn', message: 'Nguồn đã truy xuất chưa trả lời đủ nội dung bạn hỏi.' },
  missing_provision: { title: 'Chưa tìm thấy điều khoản phù hợp', message: 'Chưa tìm thấy điều khoản phù hợp đang có hiệu lực trong các văn bản hiện có.' },
  current_law_status_unverified: { title: 'Chưa xác minh được hiệu lực hiện hành', message: 'Đã tìm thấy điều khoản, nhưng kho dữ liệu chưa xác nhận tình trạng hiệu lực hoặc các sửa đổi về sau.' },
  incomplete_issue_coverage: { title: 'Chưa đủ căn cứ cho toàn bộ vấn đề', message: 'Chưa tìm thấy căn cứ phù hợp đang có hiệu lực cho một hoặc nhiều vấn đề cần kiểm tra.' },
  failed_citation_verification: { title: 'Chưa kiểm tra được căn cứ', message: 'Trợ lý đã dừng để không trả lời khi chưa kiểm tra được nguồn phù hợp.' },
  stale_corpus: { title: 'Văn bản cần được cập nhật', message: 'Thông tin hiện tại chưa được xác nhận là mới nhất cho các quy định liên quan.' },
  unavailable_dependencies: { title: 'Một dịch vụ đang tạm thời không khả dụng', message: 'Hệ thống chưa thể kiểm tra đầy đủ. Bạn có thể thử lại sau ít phút.' },
  invalid_or_unresolved_fact: { title: 'Thông tin chưa đủ rõ để kết luận', message: 'Một thông tin chưa hợp lệ hoặc chưa được xác định rõ trong phạm vi hỗ trợ hiện tại.' },
};

const errorCopy: Record<string, { title: string; fallback: string }> = {
  authentication_required: { title: 'Phiên đăng nhập cần được làm mới', fallback: 'Hãy đăng nhập lại để tiếp tục.' },
  unauthorized: { title: 'Bạn chưa được phép thực hiện thao tác này', fallback: 'Hãy kiểm tra tài khoản hoặc quyền truy cập của bạn.' },
  rate_limited: { title: 'Bạn đang gửi yêu cầu hơi nhanh', fallback: 'Vui lòng chờ một chút rồi thử lại.' },
  rate_limit_exceeded: { title: 'Bạn đang gửi yêu cầu hơi nhanh', fallback: 'Vui lòng chờ một chút rồi thử lại.' },
  corpus_not_ready: { title: 'Văn bản pháp luật chưa sẵn sàng', fallback: 'Tra cứu pháp luật tạm thời chưa thể sử dụng. Lịch sử trò chuyện vẫn được giữ nguyên.' },
  corpus_promotion_blocked: { title: 'Dữ liệu pháp luật chưa sẵn sàng', fallback: 'Chức năng sẽ khả dụng sau khi kiểm tra kỹ thuật dữ liệu hoàn tất.' },
  database_unavailable: { title: 'Lịch sử tạm thời không khả dụng', fallback: 'Hãy thử lại sau ít phút.' },
  persistence_failed: { title: 'Không thể lưu lượt trao đổi', fallback: 'Nội dung chưa được ghi nhận đầy đủ. Hãy thử lại.' },
  web_provider_unavailable: { title: 'Nguồn bổ sung đang tạm thời không khả dụng', fallback: 'Bạn có thể thử lại sau hoặc tiếp tục với kho văn bản hiện có.' },
  stream_incomplete: { title: 'Câu trả lời bị gián đoạn', fallback: 'Hệ thống chưa nhận đủ nội dung trả lời. Bạn có thể thử lại.' },
  pipeline_unavailable: { title: 'Dịch vụ trả lời đang bận', fallback: 'Hãy thử lại sau ít phút.' },
  capacity_exceeded: { title: 'Hệ thống đang xử lý nhiều yêu cầu', fallback: 'Vui lòng chờ vài giây rồi thử lại.' },
  capacity_unavailable: { title: 'Chưa thể kiểm tra năng lực xử lý', fallback: 'Vui lòng thử lại sau ít phút.' },
  pipeline_error: { title: 'Không thể hoàn tất câu trả lời', fallback: 'Hãy thử lại hoặc thu hẹp câu hỏi.' },
};

export function errorPresentation(error: StreamError): { title: string; message: string } {
  const copy = errorCopy[error.code] || errorCopy.pipeline_error;
  return { title: copy.title, message: copy.fallback };
}
