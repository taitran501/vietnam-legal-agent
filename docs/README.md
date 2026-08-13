# Tài liệu kiến trúc và vận hành

Đây là mục lục tài liệu của EPR Chatbot. Ứng dụng chỉ hỗ trợ tra cứu và
đánh giá sơ bộ pháp luật EPR Việt Nam; tài liệu này không thay thế văn bản
pháp luật hoặc ý kiến tư vấn pháp lý.

## Source of truth

- **Behavior contract:** [pipeline_v4_behavior_contract.md](pipeline_v4_behavior_contract.md)
  mô tả hành vi mà backend phải giữ ổn định.
- **Domain contract:** mã nguồn trong `src/epr_agent/domain/`, đặc biệt
  `v4.py` và `epr_rules.py` (`CaseFormResolver`), là nguồn duy nhất cho field,
  dependency, validation và trạng thái hồ sơ. Route
  `backend/api/routes/case_form.py` chỉ là adapter HTTP side-effect-free.
- **API contract:** schema Pydantic trong `backend/api/schemas.py` và các route
  trong `backend/api/routes/` là nguồn cho request/response công khai.
- **UI contract:** các component và test trong `frontend-react/src/` mô tả
  cách một người dùng phổ thông đi qua sản phẩm.
- **Release evidence:** acceptance reports chỉ ghi nhận commit và môi trường
  thực sự đã được kiểm tra; không sửa báo cáo cũ để biến một release chưa test
  thành đã đạt.

## Bản đồ tài liệu

### Kiến trúc

- [Tổng quan hệ thống](architecture/system-overview.md)
- [Luồng guided form](architecture/guided-user-flows.md)
- [Mô hình domain](architecture/domain-model.md)
- [Chiến lược kiểm thử](architecture/testing-strategy.md)
- [Các quyết định kiến trúc](architecture/decisions/)

### Retrieval và behavior

- [V4 behavior contract](pipeline_v4_behavior_contract.md)
- [V4 test matrix](v4_test_matrix.md)
- [RAG pipeline](rag_pipeline.md)
- [Retrieval](retrieval/README.md)

### Vận hành

- [Local preview](runbooks/local-preview.md)
- [Database migration](runbooks/database-migration.md)
- [Production promotion](runbooks/production-promotion.md)
- [Rollback](runbooks/rollback.md)

### Acceptance

- [Acceptance report](acceptance_report.md)
- [Browser acceptance report](browser_acceptance_report.md)
- [Guided user experience browser acceptance](browser_acceptance_report_guided_user_experience.md)
- [V4 acceptance report](pipeline_v4_acceptance_report.md)

Các sơ đồ Mermaid được đặt trực tiếp trong Markdown để GitHub render và để
reviewer có thể review thay đổi kiến trúc cùng thay đổi code.
