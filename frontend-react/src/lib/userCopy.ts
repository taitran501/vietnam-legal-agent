import type { CaseField, CaseState, StreamError } from '@/types';

export type UserTaskCopy = {
  title: string;
  action: string;
  description: string;
};

export const taskCopy: Record<CaseState['task_type'], UserTaskCopy> = {
  assess_epr_obligation: {
    title: 'Kiểm tra trường hợp của doanh nghiệp',
    action: 'Kiểm tra trường hợp',
    description: 'Điền các thông tin liên quan. Trợ lý sẽ đối chiếu căn cứ và nêu kết luận sơ bộ.',
  },
  build_compliance_checklist: {
    title: 'Tạo danh sách việc cần làm',
    action: 'Tạo danh sách việc cần làm',
    description: 'Cho biết phạm vi hoạt động để nhận danh sách việc cần chuẩn bị và căn cứ đối chiếu.',
  },
};

export const factLabels: Record<string, string> = {
  business_role: 'vai trò doanh nghiệp',
  product_or_packaging: 'sản phẩm hoặc bao bì',
  material: 'vật liệu chính',
  activity_scope: 'phạm vi hoạt động',
  object_kind: 'loại đối tượng',
  product_group: 'nhóm sản phẩm EPR',
  packaged_goods_category: 'nhóm hàng hóa được đóng gói',
  market_placement: 'phạm vi đưa ra thị trường',
  activity_purpose: 'mục đích hoạt động',
  annual_revenue_vnd: 'doanh thu liên quan',
  reused_by_producer: 'việc thu hồi và tái sử dụng',
  recovery_rate: 'tỷ lệ thu hồi và tái sử dụng',
};

const fieldOptions: Record<string, Array<{ value: string; label: string }>> = {
  business_role: [{ value: 'manufacturer', label: 'Nhà sản xuất' }, { value: 'importer', label: 'Nhà nhập khẩu' }],
  object_kind: [{ value: 'product', label: 'Sản phẩm' }, { value: 'commercial_packaging', label: 'Bao bì thương phẩm' }, { value: 'raw_material', label: 'Nguyên liệu' }, { value: 'production_waste', label: 'Chất thải sản xuất' }],
  product_group: [{ value: 'bao_bi', label: 'Bao bì' }, { value: 'ac_quy', label: 'Ắc quy' }, { value: 'pin', label: 'Pin' }, { value: 'dau_nhot', label: 'Dầu nhớt' }, { value: 'sam_lop', label: 'Săm lốp' }, { value: 'dien_tu', label: 'Điện - điện tử' }, { value: 'phuong_tien', label: 'Phương tiện' }],
  packaged_goods_category: [{ value: 'thuc_pham', label: 'Thực phẩm' }, { value: 'my_pham', label: 'Mỹ phẩm' }, { value: 'thuoc', label: 'Thuốc' }, { value: 'phan_bon_thuc_an_thu_y', label: 'Phân bón/thức ăn chăn nuôi/thuốc thú y' }, { value: 'che_pham_tay_rua', label: 'Chế phẩm tẩy rửa' }, { value: 'xi_mang', label: 'Xi măng' }, { value: 'other', label: 'Khác' }],
  material: [{ value: 'plastic', label: 'Nhựa' }, { value: 'pet', label: 'Nhựa PET' }, { value: 'pe_pp', label: 'Nhựa PE/PP' }, { value: 'paper', label: 'Giấy' }, { value: 'glass', label: 'Thủy tinh' }, { value: 'metal', label: 'Kim loại' }, { value: 'rubber', label: 'Cao su' }],
  market_placement: [{ value: 'vietnam_market', label: 'Đưa ra thị trường Việt Nam' }, { value: 'export_only', label: 'Chỉ xuất khẩu' }, { value: 'temporary_import_reexport', label: 'Tạm nhập - tái xuất' }],
  activity_purpose: [{ value: 'commercial', label: 'Kinh doanh thương mại' }, { value: 'research_study_test', label: 'Nghiên cứu/học tập/thử nghiệm' }],
  reused_by_producer: [{ value: 'yes', label: 'Có' }, { value: 'no', label: 'Không' }],
};

const fieldDisplayLabels: Record<string, string> = {
  business_role: 'Vai trò doanh nghiệp',
  object_kind: 'Loại đối tượng',
  product_group: 'Nhóm sản phẩm EPR',
  packaged_goods_category: 'Nhóm hàng hóa được đóng gói',
  material: 'Vật liệu hoặc quy cách',
  market_placement: 'Phạm vi đưa ra thị trường',
  activity_purpose: 'Mục đích sản xuất hoặc nhập khẩu',
  annual_revenue_vnd: 'Doanh thu bán sản phẩm liên quan mỗi năm',
  reused_by_producer: 'Bao bì có được doanh nghiệp thu hồi để tái sử dụng không',
  recovery_rate: 'Tỷ lệ thu hồi và tái sử dụng',
};

export function fieldLabelForKey(key: string, label = ''): string {
  return label && !label.includes('_') ? label : fieldDisplayLabels[key] || factLabels[key] || 'Thông tin bổ sung';
}

export function fieldOptionsForKey(key: string, options: Array<{ value: string; label: string }> = []): Array<{ value: string; label: string }> {
  const fallback = fieldOptions[key] || [];
  const labels = new Map(fallback.map((item) => [item.value, item.label]));
  return (options.length ? options : fallback).map((item) => ({
    ...item,
    label: labels.get(item.value) || (item.label.includes('_') ? item.value : item.label),
  }));
}

export function displayFactLabel(key: string, fields: CaseField[] = []): string {
  const field = fields.find((item) => item.key === key);
  return fieldLabelForKey(key, field?.label);
}

export function displayFactValue(key: string, value: string, fields: CaseField[] = []): string {
  if (key === 'annual_revenue_vnd' && /^\d+$/.test(value)) {
    return `${new Intl.NumberFormat('vi-VN').format(Number(value))} VNĐ`;
  }
  if (key === 'recovery_rate' && value) return `${value}%`;
  const field = fields.find((item) => item.key === key);
  const option = field?.options.find((item) => item.value === value);
  return option?.label || value.split('_').join(' ');
}

export const safeStopCopy: Record<string, { title: string; message: string }> = {
  out_of_scope: { title: 'Ngoài phạm vi hỗ trợ', message: 'Yêu cầu này không thuộc phạm vi pháp luật EPR mà trợ lý đang hỗ trợ.' },
  insufficient_evidence: { title: 'Chưa đủ căn cứ để trả lời chắc chắn', message: 'Một hoặc nhiều vấn đề bắt buộc chưa có nguồn hoạt động phù hợp để kiểm chứng.' },
  missing_provision: { title: 'Chưa tìm thấy điều khoản phù hợp', message: 'Kho pháp luật hiện tại chưa có nguồn hoạt động đủ cụ thể cho yêu cầu này.' },
  incomplete_issue_coverage: { title: 'Chưa đủ căn cứ cho toàn bộ vấn đề', message: 'Một hoặc nhiều vấn đề bắt buộc chưa có nguồn hoạt động phù hợp để kiểm chứng.' },
  failed_citation_verification: { title: 'Không xác minh được trích dẫn', message: 'Câu trả lời đã được dừng vì nguồn hoặc vị trí trích dẫn chưa vượt qua kiểm tra.' },
  stale_corpus: { title: 'Kho văn bản cần cập nhật', message: 'Dữ liệu pháp luật hiện tại chưa được xác nhận là mới nhất cho chuỗi sửa đổi.' },
  unavailable_dependencies: { title: 'Một dịch vụ đang tạm thời không khả dụng', message: 'Hãy thử lại sau; hệ thống chưa đưa ra kết luận khi phụ thuộc cần thiết chưa sẵn sàng.' },
  invalid_or_unresolved_fact: { title: 'Thông tin chưa đủ rõ để kết luận', message: 'Một giá trị chưa hợp lệ hoặc thuộc nhóm chưa được xác định trong phạm vi hỗ trợ hiện tại.' },
};

const errorCopy: Record<string, { title: string; fallback: string }> = {
  authentication_required: { title: 'Phiên đăng nhập cần được làm mới', fallback: 'Hãy đăng nhập lại để tiếp tục.' },
  unauthorized: { title: 'Bạn chưa được phép thực hiện thao tác này', fallback: 'Hãy kiểm tra tài khoản hoặc quyền truy cập của bạn.' },
  rate_limited: { title: 'Bạn đang gửi yêu cầu hơi nhanh', fallback: 'Vui lòng chờ một chút rồi thử lại.' },
  rate_limit_exceeded: { title: 'Bạn đang gửi yêu cầu hơi nhanh', fallback: 'Vui lòng chờ một chút rồi thử lại.' },
  corpus_not_ready: { title: 'Kho văn bản chưa sẵn sàng', fallback: 'Tra cứu pháp luật đang tạm khóa. Lịch sử trò chuyện vẫn được giữ nguyên.' },
  corpus_promotion_blocked: { title: 'Kho văn bản chưa được phê duyệt', fallback: 'Kết luận pháp lý đang tạm khóa cho đến khi dữ liệu được kiểm tra.' },
  database_unavailable: { title: 'Lịch sử tạm thời không khả dụng', fallback: 'Hãy thử lại sau ít phút.' },
  persistence_failed: { title: 'Không thể lưu lượt trao đổi', fallback: 'Nội dung chưa được ghi nhận đầy đủ. Hãy thử lại.' },
  web_provider_unavailable: { title: 'Nguồn bổ sung đang tạm thời không khả dụng', fallback: 'Bạn có thể thử lại sau hoặc tiếp tục với kho văn bản hiện có.' },
  stream_incomplete: { title: 'Câu trả lời bị gián đoạn', fallback: 'Hệ thống chưa nhận đủ nội dung trả lời. Bạn có thể thử lại.' },
  pipeline_unavailable: { title: 'Dịch vụ trả lời đang bận', fallback: 'Hãy thử lại sau ít phút.' },
  pipeline_error: { title: 'Không thể hoàn tất câu trả lời', fallback: 'Hãy thử lại hoặc thu hẹp câu hỏi.' },
};

export function errorPresentation(error: StreamError): { title: string; message: string } {
  const copy = errorCopy[error.code] || errorCopy.pipeline_error;
  const message = error.message && !/^HTTP \d{3}$/i.test(error.message) ? error.message : copy.fallback;
  return { title: copy.title, message };
}
