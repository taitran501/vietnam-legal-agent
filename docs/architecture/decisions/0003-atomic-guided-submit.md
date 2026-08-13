# ADR 0003: Guided submit dùng atomic chat turn

- **Status:** accepted
- **Context:** flow cũ PATCH hồ sơ rồi mới gửi `continue_case`, tạo thêm request,
  dễ mất đồng bộ và tạo cảm giác phải lưu nhiều lần.
- **Decision:** guided form gửi typed `fact_updates` trực tiếp vào `/chat`. Backend
  validate, merge, persist case và evaluate trong cùng durable turn. PATCH chỉ
  dành cho full editor/save-for-later và compatibility.
- **Consequences:** replay descriptor phải giữ nguyên facts và intent; transaction
  boundary rõ hơn; form cần khóa trong lúc submit.
