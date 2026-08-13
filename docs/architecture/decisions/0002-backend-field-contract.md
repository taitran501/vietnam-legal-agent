# ADR 0002: Backend là nguồn duy nhất của dependency và validation

- **Status:** accepted
- **Context:** frontend và V4 từng có các bản sao khác nhau của required field,
  revenue limit và conditional packaging fields.
- **Decision:** `CaseFormResolver` là service thuần, dùng bởi resolve endpoint,
  session PATCH và V4 runtime. Frontend chỉ render metadata và hiển thị lỗi.
- **Consequences:** rule thay đổi ở một nơi; UI phụ thuộc vào API contract và
  phải giữ draft khi resolve lỗi.
- **Rejected:** frontend tự suy ra field phụ thuộc bằng danh sách hard-code.
