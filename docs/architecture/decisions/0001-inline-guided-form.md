# ADR 0001: Inline guided form thay cho drawer-first

- **Status:** accepted
- **Context:** người dùng phổ thông phải mở drawer nhiều lần để bổ sung từng
  field, dù backend đã biết danh sách thông tin còn thiếu.
- **Decision:** form thích ứng hiển thị ngay trong welcome screen hoặc assistant
  message mới nhất. Một card active nhận input và có một nút submit chính.
- **Consequences:** giảm click và giữ ngữ cảnh; card lịch sử phải read-only,
  và UI cần xử lý dynamic fields. Drawer vẫn tồn tại cho full editor/save-for-later.
- **Rejected:** bắt người dùng mở drawer sau mỗi câu hỏi follow-up.
