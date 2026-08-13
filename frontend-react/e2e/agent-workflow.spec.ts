import { expect, test, type Page } from '@playwright/test';

async function mockBaseApi(page: Page) {
  await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, body: '{}' }));
  await page.route('**/api/v1/ready', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'ready',
      runtime_mode: 'preview',
      preview: true,
      dependencies: { database: 'ok', redis: 'ok', qdrant: 'ok', openai: 'ok' },
      capabilities: {
        history: { status: 'ready', reason: 'ok' },
        legal_chat: { status: 'ready', reason: 'preview_unapproved_corpus' },
        case_workflow: { status: 'ready', reason: 'preview_unapproved_corpus' },
        feedback: { status: 'ready', reason: 'ok' },
        web_research: { status: 'degraded', reason: 'provider_not_configured' },
      },
      corpus: { status: 'preview_ready', corpus_id: 'epr' },
    }),
  }));
  await page.route('**/api/v1/sessions?*', (route) => route.fulfill({ status: 200, body: '[]' }));
  await page.route('**/api/v1/sessions', (route) => route.fulfill({ status: 200, body: '[]' }));
}

function eventStream(events: Array<Record<string, unknown>>): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
}

async function captureReview(page: Page, name: string) {
  if (process.env.CAPTURE_UI !== '1') return;
  await page.waitForTimeout(260);
  await page.screenshot({ path: `../output/playwright/${name}.png`, fullPage: false });
}

test('missing-facts trajectory stops safely and opens contextual case data', async ({ page }) => {
  await mockBaseApi(page);
  let chatCalls = 0;
  await page.route('**/api/v1/chat', (route) =>
    (chatCalls += 1, route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        { type: 'status', stage: 'turn_started', turn_id: 'turn-1', user_message_id: 1, assistant_message_id: 2, turn_status: 'streaming' },
        { type: 'workflow_step', step: 1, action: 'understand_task', status: 'completed' },
        { type: 'workflow_step', step: 2, action: 'ask_user', status: 'completed' },
        { type: 'response_chunk', chunk: 'Bạn cho biết thêm vật liệu chính.' },
        {
          type: 'response_complete',
          text: 'Bạn cho biết thêm vật liệu chính.',
          documents: [],
          source: 'follow_up',
          task_type: 'assess_epr_obligation',
          case_state: {
            task_type: 'assess_epr_obligation',
            status: 'collecting',
            facts: { business_role: 'nhà sản xuất' },
            missing_facts: ['product_or_packaging', 'material', 'activity_scope'],
            fields: [
              { key: 'business_role', label: 'Vai trò doanh nghiệp', kind: 'text', options: [], required: true, missing: false, value: 'nhà sản xuất' },
              { key: 'material', label: 'Vật liệu hoặc quy cách', kind: 'text', options: [], required: true, missing: true, value: '' },
            ],
          },
          missing_facts: ['product_or_packaging', 'material', 'activity_scope'],
          citations: [],
          outcome: 'needs_information',
          result_type: 'none',
          termination_reason: 'awaiting_user_input',
          assistant_message_id: 2,
        },
      ]),
    }))
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Kiểm tra nghĩa vụ' }).click();
  await expect(page.getByLabel('Câu hỏi pháp lý')).toHaveValue('Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?');
  expect(chatCalls).toBe(0);
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();

  const result = page.getByRole('region', { name: 'Kết quả workflow' });
  await expect(result.getByText('Cần thêm thông tin để tiếp tục')).toBeVisible();
  await result.getByRole('button', { name: 'Bổ sung trong bảng thông tin' }).click();

  const drawer = page.getByRole('dialog', { name: 'Thông tin tình huống' });
  await expect(drawer.getByText('Thông tin đã xác nhận')).toBeVisible();
  await expect(drawer.getByText('Vật liệu hoặc quy cách')).toBeVisible();
  expect((await drawer.boundingBox())?.width).toBeGreaterThanOrEqual(390);
  await captureReview(page, 'integrated-missing-facts-drawer');
  await drawer.getByRole('button', { name: 'Đóng' }).click();

  await page.getByRole('button', { name: /Đã hoàn tất 2 bước/ }).click();
  await expect(page.getByText('Hiểu yêu cầu')).toBeVisible();
});

test('safe-stop trajectory never renders a legal conclusion', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        { type: 'status', stage: 'turn_started', turn_id: 'turn-2', user_message_id: 3, assistant_message_id: 4, turn_status: 'streaming' },
        { type: 'response_chunk', chunk: 'Chưa đủ tài liệu để kết luận.' },
        {
          type: 'response_complete',
          text: 'Chưa đủ tài liệu để kết luận.',
          documents: [],
          source: 'error',
          task_type: 'legal_lookup',
          citations: [],
          termination_reason: 'insufficient_evidence',
          assistant_message_id: 4,
        },
      ]),
    })
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Tra cứu quy định' }).click();
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();

  const result = page.getByRole('region', { name: 'Kết quả workflow' });
  await expect(result.getByText('Chưa đủ căn cứ để trả lời chắc chắn')).toBeVisible();
  await expect(result.getByText('Đánh giá sơ bộ', { exact: true })).not.toBeVisible();
});

test('completed legal lookup reveals its evidence in a temporary source drawer', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        { type: 'status', stage: 'turn_started', turn_id: 'turn-3', user_message_id: 5, assistant_message_id: 6, turn_status: 'streaming' },
        { type: 'workflow_step', step: 1, action: 'retrieve_legal', status: 'completed' },
        { type: 'response_chunk', chunk: 'Điều 77 quy định trách nhiệm tái chế.' },
        {
          type: 'response_complete',
          text: 'Điều 77 quy định trách nhiệm tái chế [1].',
          source: 'legal',
          task_type: 'legal_lookup',
          documents: [
            {
              page_content: 'Nhà sản xuất, nhập khẩu có trách nhiệm tái chế sản phẩm, bao bì.',
              document_id: 'law-77',
              score: 0.93,
              source: 'legal',
              metadata: { Dieu: 'Điều 77', source: 'Nghị định 08/2022/NĐ-CP' },
            },
          ],
          citations: [{ index: 1, label: 'Điều 77' }],
          termination_reason: 'completed',
          assistant_message_id: 6,
        },
      ]),
    })
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Tra cứu quy định' }).click();
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();
  await captureReview(page, 'integrated-completed-answer');
  await page.getByRole('link', { name: '[1]' }).click();

  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  await expect(drawer.getByText('Nghị định 08/2022/NĐ-CP')).toBeVisible();
  await expect(drawer.getByText(/Điều 77/)).toBeVisible();
  await expect(page.locator('#source-1')).toBeFocused();
  expect((await drawer.boundingBox())?.width).toBeGreaterThanOrEqual(390);
  await captureReview(page, 'integrated-source-drawer');
  await drawer.getByRole('button', { name: 'Đóng' }).click();
  await expect(drawer).not.toBeVisible();
});

test('mobile welcome uses a drawer for history and never overflows horizontally', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockBaseApi(page);
  await page.goto('/');

  await expect(page.getByRole('heading', { name: /Hôm nay bạn muốn tìm hiểu/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await captureReview(page, 'integrated-welcome-mobile');

  await page.getByRole('button', { name: 'Mở lịch sử trò chuyện' }).click();
  const sidebar = page.getByRole('complementary', { name: 'Lịch sử trò chuyện' });
  await expect(sidebar.getByRole('button', { name: 'Cuộc trò chuyện mới' })).toBeVisible();
  await sidebar.getByRole('button', { name: 'Đóng lịch sử' }).click();
  await expect(sidebar).not.toBeVisible();
});

test('mobile conversation keeps the answer and composer inside the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        { type: 'status', stage: 'turn_started', turn_id: 'turn-4', user_message_id: 7, assistant_message_id: 8, turn_status: 'streaming' },
        { type: 'response_chunk', chunk: 'Điều 77 quy định trách nhiệm tái chế.' },
        {
          type: 'response_complete',
          text: 'Điều 77 quy định trách nhiệm tái chế.',
          documents: [],
          source: 'legal',
          task_type: 'legal_lookup',
          citations: [],
          termination_reason: 'completed',
          assistant_message_id: 8,
        },
      ]),
    })
  );

  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Điều 77 quy định gì?');
  await input.press('Enter');

  await expect(page.getByText('Điều 77 quy định trách nhiệm tái chế.', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const composer = await page.getByLabel('Câu hỏi pháp lý').boundingBox();
  expect(composer).not.toBeNull();
  expect((composer?.x || 0) + (composer?.width || 0)).toBeLessThanOrEqual(390);
  await captureReview(page, 'integrated-conversation-mobile');
});

test('tablet uses an icon rail and expands history as a temporary drawer', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 1024 });
  await mockBaseApi(page);
  await page.goto('/');

  await expect(page.getByLabel('Thanh điều hướng thu gọn')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await captureReview(page, 'integrated-welcome-tablet');

  await page.getByRole('button', { name: 'Mở thanh lịch sử' }).click();
  await expect(page.getByRole('complementary', { name: 'Lịch sử trò chuyện' })).toBeVisible();
});

test('desktop history can collapse into the intentional icon rail', async ({ page }) => {
  await mockBaseApi(page);
  await page.goto('/');
  await captureReview(page, 'integrated-welcome-desktop');

  await page.getByRole('button', { name: 'Thu gọn thanh lịch sử' }).click();
  await expect(page.getByRole('button', { name: 'Mở thanh lịch sử' })).toBeVisible();
  await expect(page.getByLabel('Thanh điều hướng thu gọn')).toBeVisible();
  await captureReview(page, 'integrated-welcome-desktop-collapsed');
});

test('direct URL, root reset, and browser back follow the URL without stale content', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/sessions/route-1/case', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: 'null' }));
  await page.route('**/api/v1/sessions/route-1', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: 'route-1',
      title: 'Điều hướng',
      created_at: 1,
      message_count: 2,
      messages: [
        { id: 21, role: 'user', content: 'Câu hỏi của route 1', timestamp: '2026-08-13T00:00:00Z', status: 'complete' },
        { id: 22, role: 'assistant', content: 'Nội dung chỉ thuộc route 1', timestamp: '2026-08-13T00:00:01Z', status: 'complete', metadata: {} },
      ],
    }),
  }));

  await page.goto('/conversations/route-1');
  await expect(page.getByText('Nội dung chỉ thuộc route 1')).toBeVisible();
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Hôm nay bạn muốn tìm hiểu/ })).toBeVisible();
  await expect(page.getByText('Nội dung chỉ thuộc route 1')).not.toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/conversations\/route-1$/);
  await expect(page.getByText('Nội dung chỉ thuộc route 1')).toBeVisible();
});

test('session network failure keeps the URL and exposes an explicit retry', async ({ page }) => {
  await mockBaseApi(page);
  let recovered = false;
  await page.route('**/api/v1/sessions/network-case/case', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: 'null' }));
  await page.route('**/api/v1/sessions/network-case', (route) => {
    if (!recovered) return route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'network-case', title: 'Khôi phục', created_at: 1, message_count: 1,
        messages: [{ id: 31, role: 'assistant', content: 'Đã tải lại thành công', timestamp: '2026-08-13T00:00:00Z', status: 'complete', metadata: {} }],
      }),
    });
  });

  await page.goto('/conversations/network-case');
  await expect(page.getByRole('alert').getByText('Không thể tải cuộc trò chuyện', { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/conversations\/network-case$/);
  recovered = true;
  await page.getByRole('alert').getByRole('button', { name: 'Thử lại' }).click();
  await expect(page.getByText('Đã tải lại thành công')).toBeVisible();
});

test('regeneration failure preserves the accepted answer and retry reuses the replay target', async ({ page }) => {
  await mockBaseApi(page);
  let chatCalls = 0;
  const requestBodies: Array<Record<string, unknown>> = [];
  await page.route('**/api/v1/chat', async (route) => {
    chatCalls += 1;
    requestBodies.push(route.request().postDataJSON() as Record<string, unknown>);
    if (chatCalls === 2) {
      return route.fulfill({
        status: 503,
        contentType: 'text/event-stream',
        body: eventStream([{ type: 'error', code: 'pipeline_unavailable', message: 'Dịch vụ tạm thời không khả dụng.', retryable: true, retry_after_seconds: 0 }]),
      });
    }
    const replacement = chatCalls === 3;
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        { type: 'status', stage: 'turn_started', turn_id: `regen-${chatCalls}`, user_message_id: 40, assistant_message_id: replacement ? 42 : 41, turn_status: 'streaming' },
        { type: 'response_chunk', chunk: replacement ? 'Câu trả lời thay thế.' : 'Câu trả lời đã chấp nhận.' },
        { type: 'response_complete', text: replacement ? 'Câu trả lời thay thế.' : 'Câu trả lời đã chấp nhận.', source: 'legal', documents: [], citations: [], assistant_message_id: replacement ? 42 : 41, outcome: 'completed', result_type: 'legal_answer' },
      ]),
    });
  });

  await page.goto('/');
  await page.getByLabel('Câu hỏi pháp lý').fill('Điều 77 là gì?');
  await page.getByLabel('Câu hỏi pháp lý').press('Enter');
  await expect(page.getByText('Câu trả lời đã chấp nhận.')).toBeVisible();
  await page.getByRole('button', { name: 'Tạo lại câu trả lời' }).click();
  await expect(page.getByText('Câu trả lời đã chấp nhận.')).toBeVisible();
  await expect(page.getByText('Đã xảy ra lỗi khi xử lý')).toHaveCount(1);
  await expect(page.getByText(/HTTP 500/)).toHaveCount(0);
  await page.getByRole('button', { name: 'Thử lại' }).click();
  await expect(page.getByText('Câu trả lời thay thế.')).toBeVisible();
  await expect(page.getByText('Câu trả lời đã chấp nhận.')).not.toBeVisible();
  expect(requestBodies[1].operation).toBe('regenerate');
  expect(requestBodies[2].operation).toBe('regenerate');
  expect(requestBodies[1].target_assistant_message_id).toBe(41);
  expect(requestBodies[2].target_assistant_message_id).toBe(41);
});

test('task type is saved before checklist continuation and drawer closes only after acceptance', async ({ page }) => {
  await mockBaseApi(page);
  let chatCalls = 0;
  let continuationBody: Record<string, unknown> | null = null;
  let patchBody: Record<string, unknown> | null = null;
  const readyCase = {
    task_type: 'assess_epr_obligation',
    status: 'ready',
    facts: { business_role: 'manufacturer' },
    missing_facts: [],
    last_query: 'Tôi có nghĩa vụ EPR không?',
    fields: [{ key: 'business_role', label: 'Vai trò doanh nghiệp', kind: 'select', options: [{ value: 'manufacturer', label: 'Nhà sản xuất' }], required: true, missing: false, value: 'manufacturer' }],
  };
  await page.route('**/api/v1/sessions/*/case', async (route) => {
    if (route.request().method() !== 'PATCH') return route.fallback();
    patchBody = route.request().postDataJSON() as Record<string, unknown>;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...readyCase, task_type: 'build_compliance_checklist' }) });
  });
  await page.route('**/api/v1/chat', async (route) => {
    chatCalls += 1;
    if (chatCalls === 2) continuationBody = route.request().postDataJSON() as Record<string, unknown>;
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream(chatCalls === 1 ? [
        { type: 'status', stage: 'turn_started', turn_id: 'case-1', user_message_id: 51, assistant_message_id: 52, turn_status: 'streaming' },
        { type: 'response_complete', text: 'Hồ sơ đã sẵn sàng.', source: 'follow_up', documents: [], citations: [], assistant_message_id: 52, case_state: readyCase, outcome: 'needs_information', result_type: 'none' },
      ] : [
        { type: 'status', stage: 'turn_started', turn_id: 'case-2', user_message_id: 53, assistant_message_id: 54, turn_status: 'streaming' },
        { type: 'response_complete', text: 'Đã lập checklist.', source: 'legal', documents: [], citations: [], assistant_message_id: 54, checklist: [{ item: 'Đối chiếu Điều 77', action: 'Kiểm tra hồ sơ' }], outcome: 'completed', result_type: 'checklist' },
      ]),
    });
  });

  await page.goto('/');
  await page.getByLabel('Câu hỏi pháp lý').fill('Tôi có nghĩa vụ EPR không?');
  await page.getByLabel('Câu hỏi pháp lý').press('Enter');
  await page.getByRole('button', { name: 'Mở thông tin tình huống' }).click();
  const drawer = page.getByRole('dialog', { name: 'Thông tin tình huống' });
  await drawer.getByLabel('Mục tiêu').selectOption('build_compliance_checklist');
  await drawer.getByRole('button', { name: 'Lưu và tiếp tục lập checklist' }).click();

  await expect(drawer).not.toBeVisible();
  await expect(page.getByText('Checklist đề xuất')).toBeVisible();
  expect(patchBody?.task_type).toBe('build_compliance_checklist');
  expect(continuationBody?.operation).toBe('continue_case');
  expect(continuationBody?.intent_hint).toBe('compliance_checklist');
});

test('production corpus block disables legal send but leaves owned history usable', async ({ page }) => {
  await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, body: '{}' }));
  await page.route('**/api/v1/ready', (route) => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'not_ready',
      runtime_mode: 'production',
      preview: false,
      dependencies: { database: 'ok', redis: 'error', qdrant: 'ok', openai: 'ok' },
      capabilities: {
        history: { status: 'ready', reason: 'ok' },
        legal_chat: { status: 'blocked', reason: 'corpus_promotion_blocked' },
        case_workflow: { status: 'blocked', reason: 'corpus_promotion_blocked' },
        feedback: { status: 'ready', reason: 'ok' },
        web_research: { status: 'blocked', reason: 'corpus_promotion_blocked' },
      },
      corpus: { status: 'promotion_blocked', corpus_id: 'epr' },
    }),
  }));
  await page.route('**/api/v1/sessions?*', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{ id: 'history-still-works', title: 'Lịch sử vẫn dùng được', created_at: 1, message_count: 2 }]),
  }));
  await page.route('**/api/v1/sessions', (route) => route.fulfill({ status: 200, body: '[]' }));

  await page.goto('/');
  await expect(page.getByText('Lịch sử vẫn dùng được')).toBeVisible();
  await expect(page.getByText(/Corpus chưa được phê duyệt cho production/)).toBeVisible();
  await expect(page.getByLabel('Câu hỏi pháp lý')).toBeDisabled();
  await expect(page.getByText(/Chế độ xem trước/)).toHaveCount(0);
});

test('an accepted official-web source keeps its verified outbound link and label', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: eventStream([
      { type: 'status', stage: 'turn_started', turn_id: 'web-1', user_message_id: 71, assistant_message_id: 72, turn_status: 'streaming' },
      { type: 'response_chunk', chunk: 'Nguồn chính thức ngoài corpus [1].' },
      {
        type: 'response_complete',
        text: 'Nguồn chính thức ngoài corpus [1].',
        source: 'web_search',
        documents: [{
          page_content: 'Trích đoạn chính thức đã được giới hạn độ dài.',
          document_id: 'web:official:1',
          source: 'web',
          metadata: {
            Source_Title: 'Nghị định 48/2026/NĐ-CP',
            Document_Number: '48/2026/NĐ-CP',
            legal_anchor: 'Điều 78',
            source_kind: 'official_web',
            authority: 'official',
            official_url: 'https://vanban.chinhphu.vn/?docid=216867',
          },
        }],
        citations: [{ index: 1, label: 'Điều 78' }],
        assistant_message_id: 72,
        outcome: 'completed',
        result_type: 'legal_answer',
      },
    ]),
  }));

  await page.goto('/');
  await page.getByLabel('Câu hỏi pháp lý').fill('Tìm nguồn chính thức về Điều 78');
  await page.getByLabel('Câu hỏi pháp lý').press('Enter');
  await expect(page.getByText('Nguồn chính thức ngoài corpus', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: '[1]' }).click();
  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  const outbound = drawer.getByRole('link', { name: 'Mở nguồn' });
  await expect(outbound).toHaveAttribute('href', 'https://vanban.chinhphu.vn/?docid=216867');
  await expect(drawer.getByText(/example\.com/)).toHaveCount(0);
});
