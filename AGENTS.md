# AGENT INSTRUCTIONS: VIETNAM LEGAL AGENT

## NGHIÊM CẤM (STRICTLY FORBIDDEN)
1. **NGHIÊM CẤM thêm pattern-based, hardcoded regex hay từ điển ánh xạ từ khóa (synonym maps)** vào hệ thống.
   - Không tạo bảng tra cứu kiểu: `"từ lóng A" -> "thuật ngữ luật B"`.
   - Không nhồi nhét các ví dụ mapping cụ thể vào system prompt của mô hình.
   - Mọi nỗ lực "chuẩn hóa ngôn ngữ" bằng rule-based đều bị cấm vì gây suy yếu tính tổng quát và overfitting.
2. **HẠN CHẾ TỐI ĐA if-else rule-based**:
   - Không lạm dụng các nhánh rẽ `if-else` cứng để can thiệp vào logic pháp lý hoặc điều hướng truy vấn.
   - Luồng nghiệp vụ phải giữ tính mở, để LLM và không gian vector ngữ nghĩa (semantic embedding) tự tổng quát hóa.

## NGUYÊN TẮC VẬN HÀNH (CORE PRINCIPLES)
- **Tổng quát hóa (Generalization)**: Xử lý ngôn ngữ tự nhiên thông qua Semantic Vector Space (`darklethelong/vnlegal-lal`, `vietnam_legal_collection_v1`) kết hợp BM25 RRF trên toàn bộ kho luật pháp.
- **Tối ưu Pipeline & Embedding Backend**: Giải quyết bài toán tốc độ và độ chính xác ở tầng hạ tầng (vector database, HNSW parameters, cache warmup, cascade pooling LLM).
- **Căn cứ pháp lý chuẩn xác (Evidence Grounding)**: Câu trả lời phải bám sát trích dẫn `[n]` từ các điều khoản pháp luật thực tế được truy xuất, không suy đoán ngoài căn cứ.

Xem hướng dẫn chi tiết tại skill: [no-rule-based-patterns](file:///agent/skills/no-rule-based-patterns/SKILL.md).
