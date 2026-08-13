# Guided user flows

## Luồng cuối

| Mục tiêu | Entry point | Hành động chính | Kết quả |
| --- | --- | --- | --- |
| Tra cứu quy định | Composer | Gửi câu hỏi | Trả lời và căn cứ |
| Kiểm tra trường hợp | Welcome hoặc assistant card | Điền form thích ứng, bấm **Kiểm tra trường hợp** | Đánh giá sơ bộ hoặc yêu cầu bổ sung |
| Tạo danh sách việc cần làm | Welcome hoặc assistant card | Điền form thích ứng, bấm **Tạo danh sách việc cần làm** | Checklist có hành động và căn cứ |

Drawer chỉ mở khi người dùng muốn xem hoặc chỉnh sửa toàn bộ hồ sơ. Nó không
là bước bắt buộc để hoàn tất một case.

## Mở form và resolve field

```mermaid
sequenceDiagram
    actor User as Người dùng
    participant UI as GuidedCaseCard
    participant Draft as useCaseDraft
    participant API as POST /case-form/resolve
    participant Resolver as CaseFormResolver

    User->>UI: Chọn mục tiêu đánh giá/checklist
    UI->>Draft: tạo draft rỗng
    Draft->>API: resolve(task_type, {})
    API->>Resolver: tính field cơ sở
    Resolver-->>API: CaseFormState
    API-->>Draft: fields, counts, errors
    Draft-->>UI: render field và hướng dẫn
    User->>UI: thay đổi một field
    Draft->>API: resolve sau debounce 250ms
    API->>Resolver: merge và validate
    Resolver-->>API: field phụ thuộc + counts mới
    API-->>Draft: bỏ qua nếu response đã stale
```

## Submit atomic và SSE

```mermaid
sequenceDiagram
    actor User as Người dùng
    participant UI as GuidedCaseCard
    participant API as POST /chat
    participant Store as Durable history
    participant V4 as V4 runtime
    participant Legal as Retrieval + rule pack

    User->>UI: Bấm một nút chính
    UI->>API: message/continue_case + fact_updates
    API->>Store: lưu user message + assistant placeholder
    API-->>UI: SSE status(turn_id, message ids)
    API->>V4: validate, merge, persist case
    alt còn thiếu hoặc có lỗi field
        V4-->>API: input_required + CaseFormState
        API-->>UI: SSE case_update
    else đủ dữ liệu
        V4->>Legal: retrieve active sources and evaluate issues
        Legal-->>V4: evidence assessment
        V4-->>API: structured result + source snapshots
        API->>Store: complete turn and case
        API-->>UI: response_complete
    end
```

## Missing information, retry và căn cứ

```mermaid
sequenceDiagram
    actor User as Người dùng
    participant UI as Result card
    participant API as Backend
    participant Store as History

    UI-->>User: Còn thiếu N thông tin
    User->>UI: điền field ngay trong card
    UI->>API: resolve debounce
    API-->>UI: lỗi field hoặc card ready
    User->>UI: Retry nếu request retryable
    UI->>API: replay descriptor nguyên bản
    API->>Store: giữ câu trả lời cũ đến khi bản mới hoàn tất
    User->>UI: bấm citation [n]
    UI-->>User: source drawer focus đúng nguồn n
```

## Form state

```mermaid
stateDiagram-v2
    [*] --> idle
    idle --> resolving: mở form hoặc đổi field
    resolving --> editing: resolve thành công
    resolving --> editing: resolve lỗi, giữ draft
    editing --> resolving: debounce thay đổi
    editing --> ready: không còn field bắt buộc thiếu
    ready --> submitting: bấm nút chính
    submitting --> completed: turn hoàn tất
    submitting --> needs_information: backend phát hiện dependency mới
    submitting --> failed: lỗi không retryable hoặc dependency hỏng
    failed --> submitting: Retry
```
