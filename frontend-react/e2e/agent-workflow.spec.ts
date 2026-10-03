import { expect, test, type Page } from '@playwright/test';

async function mockBaseApi(page: Page, options: { legalChatReady?: boolean } = {}) {
  await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, body: '{}' }));
  await page.route('**/api/v1/ready', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ready',
        runtime_mode: 'preview',
        preview: true,
        dependencies: {
          database: 'ok',
          redis: 'ok',
          qdrant: 'ok',
          openai: 'ok',
        },
        capabilities: {
          history: { status: 'ready', reason: 'ok' },
          legal_chat: options.legalChatReady === false ? { status: 'blocked', reason: 'universal_corpus_unavailable' } : { status: 'ready', reason: 'preview_snapshot' },
          feedback: { status: 'ready', reason: 'ok' },
          web_research: {
            status: 'degraded',
            reason: 'provider_not_configured',
          },
        },
        corpus: { status: 'preview_ready', corpus_id: 'vietnamese_law' },
      }),
    }),
  );
  await page.route('**/api/v1/sessions?*', (route) => route.fulfill({ status: 200, body: '[]' }));
  await page.route('**/api/v1/sessions', (route) => route.fulfill({ status: 200, body: '[]' }));
}

function eventStream(events: Array<Record<string, unknown>>): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
}

async function captureReview(page: Page, name: string) {
  if (process.env.CAPTURE_UI !== '1') return;
  await page.waitForTimeout(260);
  await page.screenshot({
    path: `../output/playwright/${name}.png`,
    fullPage: false,
  });
}

test('situation consultation uses normal chat and accepts a conversational follow-up', async ({ page }) => {
  await mockBaseApi(page);
  const chatRequests: Array<Record<string, unknown>> = [];
  await page.route('**/api/v1/chat', async (route) => {
    const request = route.request().postDataJSON() as Record<string, unknown>;
    chatRequests.push(request);
    const followUp = chatRequests.length > 1;
    const assistantMessageId = followUp ? 4 : 2;
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        {
          type: 'status',
          stage: 'turn_started',
          turn_id: 'turn-' + chatRequests.length,
          user_message_id: assistantMessageId - 1,
          assistant_message_id: assistantMessageId,
          turn_status: 'streaming',
        },
        {
          type: 'response_complete',
          text: followUp ? 'Mình sẽ đối chiếu quy định về tiền lương và các bước bạn có thể thực hiện.' : 'Bạn có thể cho biết công ty đã chậm trả lương trong bao lâu không?',
          source: 'legal',
          documents: [],
          citations: [],
          assistant_message_id: assistantMessageId,
          outcome: 'completed',
        },
      ]),
    });
  });

  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await expect(input).toBeVisible();
  await expect(page.getByRole('group', { name: 'Mục tiêu pháp lý' }).getByRole('button')).toHaveCount(3);
  await expect(page.getByRole('button', { name: 'Kiểm tra trường hợp của doanh nghiệp' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Tạo danh sách việc cần làm' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Tư vấn tình huống' }).click();
  await expect(input).toHaveValue('');
  await input.fill('Công ty chậm trả lương tháng này, tôi nên xử lý thế nào?');
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();

  await expect(page.getByText('Bạn có thể cho biết công ty đã chậm trả lương trong bao lâu không?', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'Thông tin tình huống' })).toHaveCount(0);
  await input.fill('Đã chậm hơn hai tuần.');
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();

  await expect(
    page.getByText('Mình sẽ đối chiếu quy định về tiền lương và các bước bạn có thể thực hiện.', {
      exact: true,
    }),
  ).toBeVisible();
  expect(chatRequests).toHaveLength(2);
  expect(chatRequests[0].query).toBe('Công ty chậm trả lương tháng này, tôi nên xử lý thế nào?');
  expect(chatRequests[0].intent_hint).toBe('case_assessment');
  expect(chatRequests[1].query).toBe('Đã chậm hơn hai tuần.');
});

test('checklist goal is a short natural-language chat prompt', async ({ page }) => {
  await mockBaseApi(page);
  let chatRequest: Record<string, unknown> | null = null;
  await page.route('**/api/v1/chat', async (route) => {
    chatRequest = route.request().postDataJSON() as Record<string, unknown>;
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        {
          type: 'status',
          stage: 'turn_started',
          turn_id: 'checklist-turn',
          user_message_id: 21,
          assistant_message_id: 22,
          turn_status: 'streaming',
        },
        {
          type: 'response_complete',
          text: 'Bạn cần chuẩn bị hồ sơ đăng ký hộ kinh doanh theo các bước sau.',
          source: 'legal',
          task_type: 'build_compliance_checklist',
          result_type: 'checklist',
          outcome: 'completed',
          checklist: [{ item: 'Chuẩn bị hồ sơ đăng ký' }],
          documents: [],
          citations: [],
          assistant_message_id: 22,
        },
      ]),
    });
  });

  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await page.getByRole('button', { name: 'Hồ sơ & thủ tục' }).click();
  await expect(input).toHaveValue('');
  await input.fill('Tôi muốn đăng ký hộ kinh doanh tại TP.HCM. Cần làm gì?');
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();

  await expect(page.getByText('Bạn cần chuẩn bị hồ sơ đăng ký hộ kinh doanh theo các bước sau.', { exact: true })).toBeVisible();
  expect(chatRequest?.query).toBe('Tôi muốn đăng ký hộ kinh doanh tại TP.HCM. Cần làm gì?');
  expect(chatRequest?.intent_hint).toBe('compliance_checklist');
});

test('general legal readiness disables every chat goal and the composer', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockBaseApi(page, { legalChatReady: false });
  await page.goto('/');

  const goals = page.getByRole('group', { name: 'Mục tiêu pháp lý' }).getByRole('button');
  await expect(goals).toHaveCount(3);
  for (const goal of await goals.all()) await expect(goal).toBeDisabled();
  await expect(page.getByLabel('Câu hỏi pháp lý')).toBeDisabled();
});

test('invalid conversation URL is treated as a real not-found route', async ({ page }) => {
  await mockBaseApi(page);
  await page.goto('/conversations/not-a-real-conversation');

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText('Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.')).toBeVisible();
  await expect(page.locator('aside').getByTitle('Cuộc trò chuyện')).toHaveCount(0);
});

test('safe-stop trajectory never renders a legal conclusion', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        {
          type: 'status',
          stage: 'turn_started',
          turn_id: 'turn-2',
          user_message_id: 3,
          assistant_message_id: 4,
          turn_status: 'streaming',
        },
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
    }),
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Tra cứu quy định pháp luật' }).click();
  await page.getByLabel('Câu hỏi pháp lý').fill('Hãy kiểm tra căn cứ pháp lý cho tình huống này.');
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();

  const result = page.getByRole('region', { name: 'Kết quả xử lý' });
  await expect(result.getByText('Chưa đủ căn cứ để trả lời chắc chắn')).toBeVisible();
  await expect(result.getByText('Đánh giá sơ bộ', { exact: true })).not.toBeVisible();
});

test('degraded web research does not expose an action that cannot run', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        {
          type: 'status',
          stage: 'turn_started',
          turn_id: 'missing-turn',
          user_message_id: 31,
          assistant_message_id: 32,
          turn_status: 'streaming',
        },
        {
          type: 'response_complete',
          text: 'Chưa đủ tài liệu để kết luận.',
          source: 'error',
          task_type: 'legal_lookup',
          result_type: 'none',
          outcome: 'insufficient_evidence',
          termination_reason: 'insufficient_evidence',
          available_actions: ['research_web'],
          preview: true,
          documents: [],
          citations: [],
          assistant_message_id: 32,
        },
      ]),
    }),
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Tra cứu quy định pháp luật' }).click();
  await page.getByLabel('Câu hỏi pháp lý').fill('Hãy kiểm tra căn cứ pháp lý cho tình huống này.');
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();

  const result = page.getByRole('region', { name: 'Kết quả xử lý' });
  await expect(result.getByText('Chưa đủ căn cứ để trả lời chắc chắn')).toBeVisible();
  await expect(page.getByText(/Bản thử nghiệm:/)).toHaveCount(0);
});

test('completed legal lookup reveals its evidence in a temporary source drawer', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        {
          type: 'status',
          stage: 'turn_started',
          turn_id: 'turn-3',
          user_message_id: 5,
          assistant_message_id: 6,
          turn_status: 'streaming',
        },
        {
          type: 'workflow_step',
          step: 1,
          action: 'retrieve_legal',
          status: 'completed',
        },
        {
          type: 'response_chunk',
          chunk: 'Điều 25 quy định thời gian thử việc tối đa.',
        },
        {
          type: 'response_complete',
          text: 'Điều 25 quy định thời gian thử việc tối đa [1].',
          source: 'legal',
          task_type: 'legal_lookup',
          documents: [
            {
              page_content: 'Người lao động có trình độ cao đẳng được thử việc tối đa sáu mươi ngày.',
              document_id: 'law-77',
              score: 0.93,
              source: 'legal',
              metadata: { Dieu: 'Điều 25', source: 'Bộ luật Lao động 2019' },
            },
          ],
          citations: [{ index: 1, label: 'Điều 25' }],
          termination_reason: 'completed',
          assistant_message_id: 6,
          preview: true,
        },
      ]),
    }),
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Tra cứu quy định pháp luật' }).click();
  await page.getByLabel('Câu hỏi pháp lý').fill('Điều 25 Bộ luật Lao động quy định gì?');
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();
  await captureReview(page, 'integrated-completed-answer');
  await page.getByRole('link', { name: '[1]' }).click();

  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  await expect(drawer.getByText(/Bản thử nghiệm:/)).toHaveCount(0);
  await expect(drawer.getByText('Bộ luật Lao động 2019')).toBeVisible();
  await expect(drawer.getByText(/Điều 25/)).toBeVisible();
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

  await expect(page.getByRole('heading', { name: 'Trợ lý Pháp luật Việt Nam', exact: true }).last()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await captureReview(page, 'integrated-welcome-mobile');

  await page.getByRole('button', { name: 'Mở lịch sử trò chuyện' }).click();
  const sidebar = page.getByRole('complementary', {
    name: 'Lịch sử trò chuyện',
  });
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
        {
          type: 'status',
          stage: 'turn_started',
          turn_id: 'turn-4',
          user_message_id: 7,
          assistant_message_id: 8,
          turn_status: 'streaming',
        },
        {
          type: 'response_chunk',
          chunk: 'Điều 25 quy định thời gian thử việc tối đa.',
        },
        {
          type: 'response_complete',
          text: 'Điều 25 quy định thời gian thử việc tối đa.',
          documents: [],
          source: 'legal',
          task_type: 'legal_lookup',
          citations: [],
          termination_reason: 'completed',
          assistant_message_id: 8,
        },
      ]),
    }),
  );

  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Điều 25 quy định gì?');
  await input.press('Enter');

  await expect(page.getByText('Điều 25 quy định thời gian thử việc tối đa.', { exact: true })).toBeVisible();
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
  await page.route('**/api/v1/sessions/route-1', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'route-1',
        title: 'Điều hướng',
        created_at: 1,
        message_count: 2,
        messages: [
          {
            id: 21,
            role: 'user',
            content: 'Câu hỏi của route 1',
            timestamp: '2026-08-13T00:00:00Z',
            status: 'complete',
          },
          {
            id: 22,
            role: 'assistant',
            content: 'Nội dung chỉ thuộc route 1',
            timestamp: '2026-08-13T00:00:01Z',
            status: 'complete',
            metadata: {},
          },
        ],
      }),
    }),
  );

  await page.goto('/conversations/route-1');
  await expect(page.getByText('Nội dung chỉ thuộc route 1')).toBeVisible();
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Trợ lý Pháp luật Việt Nam', exact: true }).last()).toBeVisible();
  await expect(page.getByText('Nội dung chỉ thuộc route 1')).not.toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/conversations\/route-1$/);
  await expect(page.getByText('Nội dung chỉ thuộc route 1')).toBeVisible();
});

test('session network failure keeps the URL and exposes an explicit retry', async ({ page }) => {
  await mockBaseApi(page);
  let recovered = false;
  await page.route('**/api/v1/sessions/network-case', (route) => {
    if (!recovered)
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: '{}',
      });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'network-case',
        title: 'Khôi phục',
        created_at: 1,
        message_count: 1,
        messages: [
          {
            id: 31,
            role: 'assistant',
            content: 'Đã tải lại thành công',
            timestamp: '2026-08-13T00:00:00Z',
            status: 'complete',
            metadata: {},
          },
        ],
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
        body: eventStream([
          {
            type: 'error',
            code: 'pipeline_unavailable',
            message: 'Dịch vụ tạm thời không khả dụng.',
            retryable: true,
            retry_after_seconds: 0,
          },
        ]),
      });
    }
    const replacement = chatCalls === 3;
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        {
          type: 'status',
          stage: 'turn_started',
          turn_id: `regen-${chatCalls}`,
          user_message_id: 40,
          assistant_message_id: replacement ? 42 : 41,
          turn_status: 'streaming',
        },
        {
          type: 'response_chunk',
          chunk: replacement ? 'Câu trả lời thay thế.' : 'Câu trả lời đã chấp nhận.',
        },
        {
          type: 'response_complete',
          text: replacement ? 'Câu trả lời thay thế.' : 'Câu trả lời đã chấp nhận.',
          source: 'legal',
          documents: [],
          citations: [],
          assistant_message_id: replacement ? 42 : 41,
          outcome: 'completed',
          result_type: 'legal_answer',
        },
      ]),
    });
  });

  await page.goto('/');
  await page.getByLabel('Câu hỏi pháp lý').fill('Điều 25 là gì?');
  await page.getByLabel('Câu hỏi pháp lý').press('Enter');
  await expect(page.getByText('Câu trả lời đã chấp nhận.')).toBeVisible();
  await page.getByRole('button', { name: 'Tạo lại câu trả lời' }).click();
  await expect(page.getByText('Câu trả lời đã chấp nhận.')).toBeVisible();
  await expect(page.getByText('Dịch vụ trả lời đang bận')).toHaveCount(1);
  await expect(page.getByText(/HTTP 500/)).toHaveCount(0);
  await page.getByRole('button', { name: 'Thử lại' }).click();
  await expect(page.getByText('Câu trả lời thay thế.')).toBeVisible();
  await expect(page.getByText('Câu trả lời đã chấp nhận.')).not.toBeVisible();
  expect(requestBodies[1].operation).toBe('regenerate');
  expect(requestBodies[2].operation).toBe('regenerate');
  expect(requestBodies[1].target_assistant_message_id).toBe(41);
  expect(requestBodies[2].target_assistant_message_id).toBe(41);
});

test('legacy legal conversation loads without restoring a domain-specific intake drawer', async ({ page }) => {
  await mockBaseApi(page);
  let retiredWorkspaceRequests = 0;
  page.on('request', (request) => {
    if (request.url().endsWith('/api/v1/sessions/legacy-history/case')) retiredWorkspaceRequests += 1;
  });
  await page.route('**/api/v1/sessions/legacy-history', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'legacy-history',
        title: 'Lịch sử cũ',
        created_at: 1,
        message_count: 2,
        messages: [
          { id: 1, role: 'user', content: 'Tôi bị cho nghỉ việc ngay mà không báo trước. Tôi có quyền lợi gì?', timestamp: '2026-08-13T00:00:00Z', status: 'complete' },
          { id: 2, role: 'assistant', content: 'Câu trả lời cũ được giữ nguyên.', timestamp: '2026-08-13T00:00:01Z', status: 'complete', metadata: {} },
        ],
      }),
    }),
  );

  await page.goto('/conversations/legacy-history');
  await expect(page.getByText('Câu trả lời cũ được giữ nguyên.')).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'Thông tin tình huống' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Mở thông tin tình huống' })).toHaveCount(0);
  expect(retiredWorkspaceRequests).toBe(0);
});

test('production corpus block disables legal send but leaves owned history usable', async ({ page }) => {
  await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, body: '{}' }));
  await page.route('**/api/v1/ready', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'not_ready',
        runtime_mode: 'production',
        preview: false,
        dependencies: {
          database: 'ok',
          redis: 'error',
          qdrant: 'ok',
          openai: 'ok',
        },
        capabilities: {
          history: { status: 'ready', reason: 'ok' },
          legal_chat: { status: 'blocked', reason: 'corpus_promotion_blocked' },
          feedback: { status: 'ready', reason: 'ok' },
          web_research: {
            status: 'blocked',
            reason: 'corpus_promotion_blocked',
          },
        },
        corpus: { status: 'promotion_blocked', corpus_id: 'vietnamese_law' },
      }),
    }),
  );
  await page.route('**/api/v1/sessions*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'history-still-works',
          title: 'Lịch sử vẫn dùng được',
          created_at: 1,
          message_count: 2,
        },
      ]),
    }),
  );
  await page.goto('/');
  await expect(page.getByText('Lịch sử vẫn dùng được')).toBeVisible();
  await expect(page.getByText(/Dữ liệu pháp luật hiện chưa sẵn sàng để thực hiện thao tác này/)).toBeVisible();
  await expect(page.getByLabel('Câu hỏi pháp lý')).toBeDisabled();
  await expect(page.getByText(/Chế độ xem trước/)).toHaveCount(0);
});

test('an accepted official-web source keeps its verified outbound link and label', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        {
          type: 'status',
          stage: 'turn_started',
          turn_id: 'web-1',
          user_message_id: 71,
          assistant_message_id: 72,
          turn_status: 'streaming',
        },
        { type: 'response_chunk', chunk: 'Nguồn chính thức ngoài corpus [1].' },
        {
          type: 'response_complete',
          text: 'Nguồn chính thức ngoài corpus [1].',
          source: 'web_search',
          documents: [
            {
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
            },
          ],
          citations: [{ index: 1, label: 'Điều 78' }],
          assistant_message_id: 72,
          outcome: 'completed',
          result_type: 'legal_answer',
        },
      ]),
    }),
  );

  await page.goto('/');
  await page.getByLabel('Câu hỏi pháp lý').fill('Tìm nguồn chính thức về Điều 78');
  await page.getByLabel('Câu hỏi pháp lý').press('Enter');
  await expect(page.getByText('Nguồn bổ sung từ web', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: '[1]' }).click();
  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  const outbound = drawer.getByRole('link', { name: 'Mở nguồn' });
  await expect(outbound).toHaveAttribute('href', 'https://vanban.chinhphu.vn/?docid=216867');
  await expect(drawer.getByText(/example\.com/)).toHaveCount(0);
});
