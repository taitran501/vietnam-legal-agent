# ADR 0004: Technical metadata dùng progressive disclosure

- **Status:** accepted
- **Context:** người dùng thường thấy `corpus`, `workflow`, `trace` và các mã nội
  bộ trong answer, source drawer và timeline.
- **Decision:** copy mặc định dùng ngôn ngữ nghiệp vụ (“Kho văn bản pháp luật”,
  “Căn cứ”, “Thông tin doanh nghiệp”, “Chưa thể kết luận”). ID nguồn, amendment
  metadata, trace ID và version đặt trong phần thông tin đối chiếu/hỗ trợ; trace
  chỉ hiển thị khi bật debug flag.
- **Consequences:** developer vẫn có dữ liệu debug khi cần, nhưng người dùng
  phổ thông không phải hiểu kiến trúc nội bộ để hoàn thành tác vụ.
