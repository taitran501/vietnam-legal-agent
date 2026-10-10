---
name: no-rule-based-patterns
description: Nghiêm cấm thêm pattern, regex mapping, từ điển cố định và hạn chế tối đa if-else rule-based trong Vietnam Legal Agent. Đảm bảo hệ thống vận hành tổng quát dựa trên semantic retrieval, vector embedding và LLM reasoning.
---

# Nguyên Tắc Thiết Kế: Nghiêm Cấm Rule-Based Patterns & Hạn Chế If-Else Cứng

## 1. Điều Cấm Tuyệt Đối (Strictly Forbidden)
- **KHÔNG hardcode pattern-matching / regex heuristics**: Nghiêm cấm tạo các bảng ánh xạ từ khóa (keyword mapping), từ điển đồng nghĩa tĩnh (synonym dictionaries), regex pattern nhằm bắt cụ thể từng câu chữ, từ lóng hay trường hợp đời thường cụ thể (ví dụ: cấm ánh xạ cố định "con gái đi lấy chồng" -> "hàng thừa kế", cấm ánh xạ "bằng gốc" -> "văn bằng chứng chỉ").
- **KHÔNG chèn few-shot pattern mapping vào system prompts**: Nghiêm cấm đưa các ví dụ ánh xạ cụ thể dạng "từ đời thường A -> từ luật B" vào prompt của mô hình, vì điều này làm suy yếu tính tổng quát, gây overfitting và biến agent thành một hệ thống rule-based trá hình.
- **KHÔNG lạm dụng các nhánh rẽ if-else cứng (Hardcoded Branching Logic)**: Không viết các chuỗi `if-else` tầng tầng lớp lớp để can thiệp vào nghiệp vụ pháp lý, chấm điểm độ phù hợp hay điều hướng câu trả lời.

---

## 2. Nguyên Tắc Thiết Kế Cốt Lõi (Core Architectural Principles)

### 2.1. Vận hành Tổng quát (Generalization over Memorization)
- Hệ thống phải hiểu được mọi dạng ngôn ngữ tự nhiên của người dùng (từ chuẩn mực văn bản đến tiếng lóng, khẩu ngữ, drama, kể chuyện) bằng **năng lực suy luận tự nhiên của LLM** và **không gian biểu diễn ngữ nghĩa (Semantic Embedding Space)**.
- Khi người dùng hỏi một tình huống phức tạp:
  - Để LLM tự phân tích và bóc tách các khía cạnh pháp lý một cách tổng quát.
  - Sử dụng mô hình embedding (như `vnlegal-lal`, `bge-m3`) và hybrid retrieval (Vector + BM25) trên toàn bộ kho luật pháp để tìm kiếm văn bản liên quan dựa trên độ tương đồng ngữ nghĩa.

### 2.2. Tối ưu Backend Embedding & Retrieval Pipeline
- Thay vì cố gắng viết rule để "vá" các trường hợp truy xuất sai:
  - Cần tập trung tối ưu hạ tầng embedding: đảm bảo embedding model nhẹ, chạy nhanh, vector index (Qdrant) có HNSW index chất lượng cao.
  - Sử dụng cơ chế RRF (Reciprocal Rank Fusion) và ranking dựa trên điểm số ngữ nghĩa thực tế.
  - Tối ưu hóa bộ nhớ đệm (caching), nạp trước (warmup) model weights và index để giảm thiểu latency thay vì dùng quy tắc chặn dòng xử lý.

### 2.3. Đảm bảo độ chính xác qua Grounding & Verification
- Độ chính xác (Accuracy) phải đến từ việc:
  1. Kho dữ liệu pháp luật gốc đầy đủ, được lập chỉ mục chính xác (`vietnam_legal_collection_v1`).
  2. Mô hình tạo câu trả lời tuân thủ nghiêm ngặt nguyên tắc **Strict Evidence Grounding** (chỉ kết luận khi có căn cứ trong tài liệu được truy xuất).
  3. Mô hình tự động trích dẫn số hiệu điều khoản `[n]` tương ứng với văn bản thực tế.

---

## 3. Checklist Kiểm Tra Code (Code Review Checklist)
Trước khi commit bất kỳ thay đổi nào vào repo `vietnam-legal-agent`:
- [ ] File mới hoặc hàm mới có chứa từ điển ánh xạ từ khóa cố định nào không? (Nếu có -> XÓA NGAY).
- [ ] Có Regex nào được viết để bắt các câu hỏi cụ thể của người dùng không? (Nếu có -> XÓA NGAY).
- [ ] Logic điều hướng có đang dùng chuỗi `if ... in query:` để phán đoán ý định người dùng không? (Nếu có -> Chuyển giao hoàn toàn cho semantic router hoặc LLM task understanding).
- [ ] Pipeline có giữ được tính mở để tiếp nhận bất kỳ câu hỏi pháp lý mới nào thuộc mọi ngành luật của Việt Nam không?
