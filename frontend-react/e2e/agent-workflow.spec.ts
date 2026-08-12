import { expect, test, type Page } from '@playwright/test';

async function mockBaseApi(page: Page) {
  await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, body: '{}' }));
  await page.route('**/api/v1/ready', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'ready',
      dependencies: { database: 'ok', redis: 'ok', qdrant: 'ok', openai: 'ok' },
      corpus: { status: 'ready', corpus_id: 'epr' },
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
        { type: 'response_chunk', chunk: 'Chưa đủ tài liệu để kết luận.' },
        {
          type: 'response_complete',
          text: 'Chưa đủ tài liệu để kết luận.',
          documents: [],
          source: 'error',
          task_type: 'legal_lookup',
          citations: [],
          termination_reason: 'insufficient_evidence',
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
        },
      ]),
    })
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Tra cứu quy định' }).click();
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();
  await captureReview(page, 'integrated-completed-answer');
  await page.getByRole('button', { name: 'Xem 1 nguồn tham khảo' }).click();

  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  await expect(drawer.getByText('Nghị định 08/2022/NĐ-CP')).toBeVisible();
  await expect(drawer.getByText(/Điều 77/)).toBeVisible();
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
        { type: 'response_chunk', chunk: 'Điều 77 quy định trách nhiệm tái chế.' },
        {
          type: 'response_complete',
          text: 'Điều 77 quy định trách nhiệm tái chế.',
          documents: [],
          source: 'legal',
          task_type: 'legal_lookup',
          citations: [],
          termination_reason: 'completed',
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
