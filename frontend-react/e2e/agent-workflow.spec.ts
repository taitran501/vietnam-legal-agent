import { expect, test } from '@playwright/test';

async function mockBaseApi(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/health', (route) => route.fulfill({ status: 200, body: '{}' }));
  await page.route('**/api/v1/sessions?*', (route) => route.fulfill({ status: 200, body: '[]' }));
  await page.route('**/api/v1/sessions', (route) => route.fulfill({ status: 200, body: '[]' }));
}

test('assessment trajectory shows a missing-facts stop and editable case state', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: [
        'data: {"type":"workflow_step","step":1,"action":"understand_task","status":"completed"}\n\n',
        'data: {"type":"workflow_step","step":2,"action":"ask_user","status":"completed"}\n\n',
        'data: {"type":"response_chunk","chunk":"Bạn cho biết thêm vật liệu chính.\n\n"}\n\n',
        'data: {"type":"response_complete","text":"Bạn cho biết thêm vật liệu chính.","documents":[],"source":"follow_up","task_type":"assess_epr_obligation","case_state":{"task_type":"assess_epr_obligation","status":"collecting","facts":{"business_role":"nhà sản xuất"},"missing_facts":["product_or_packaging","material","activity_scope"]},"missing_facts":["product_or_packaging","material","activity_scope"],"citations":[],"termination_reason":"awaiting_user_input"}\n\n',
      ].join(''),
    })
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Đánh giá nghĩa vụ' }).click();

  const workspace = page.getByRole('main');
  await expect(workspace.getByRole('region', { name: 'Kết quả workflow' }).getByText('Cần bổ sung thông tin')).toBeVisible();
  await expect(page.getByRole('complementary').getByText('Hồ sơ trường hợp', { exact: true })).toBeVisible();
  await expect(page.getByRole('complementary').getByText('cần bổ sung').first()).toBeVisible();
  await expect(workspace.getByText('Xác định yêu cầu')).toBeVisible();
});

test('safe-stop trajectory never renders a compliance conclusion', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: [
        'data: {"type":"response_chunk","chunk":"Chưa đủ tài liệu để kết luận."}\n\n',
        'data: {"type":"response_complete","text":"Chưa đủ tài liệu để kết luận.","documents":[],"source":"error","task_type":"legal_lookup","citations":[],"termination_reason":"insufficient_evidence"}\n\n',
      ].join(''),
    })
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Tra cứu quy định' }).click();

  const result = page.getByRole('main').getByRole('region', { name: 'Kết quả workflow' });
  await expect(result.getByText('Hệ thống đã dừng an toàn')).toBeVisible();
  await expect(result.getByText('Đánh giá sơ bộ', { exact: true })).not.toBeVisible();
});
