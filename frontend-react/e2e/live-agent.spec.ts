import { expect, test } from '@playwright/test';

test('React consumes the real FastAPI SSE and opens verified legal evidence', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('EPR về bao bì được quy định như thế nào?');
  await input.press('Enter');

  await expect(page.getByText(/Theo Điều 77/)).toBeVisible();

  await page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ }).click();
  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  await expect(drawer.getByRole('heading', { name: 'Nghị định 08/2022/NĐ-CP', exact: true }).first()).toBeVisible();
  await expect(drawer.getByText('Điều 77', { exact: true })).toBeVisible();
});

test('React paints a verified answer progressively before the SSE completes', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('EPR về bao bì được quy định như thế nào?');
  await input.press('Enter');

  const streamedAnswer = page.getByTestId('streaming-answer');
  await expect(streamedAnswer).toContainText('Theo Điều 77');
  await expect(streamedAnswer).toBeVisible();
  await expect(page.getByRole('region', { name: 'Tiến trình xử lý' })).not.toBeVisible();
});

test('a user can stop an in-progress SSE response without losing rendered text', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('EPR về bao bì được quy định như thế nào?');
  await input.press('Enter');

  await expect(page.getByTestId('streaming-answer')).toContainText('Theo Điều 77');
  const stop = page.getByRole('button', { name: 'Dừng tạo câu trả lời' });
  await expect(stop).toBeVisible();
  await stop.click();

  await expect(stop).not.toBeVisible();
  await expect(page.getByTestId('streaming-answer')).not.toBeVisible();
  await expect(page.getByText(/Theo Điều 77/)).toBeVisible();
  await expect(page.getByRole('region', { name: 'Tiến trình xử lý' }).getByRole('button', { name: /Đã dừng theo yêu cầu/ })).toBeVisible();

  const sessionId = new URL(page.url()).pathname.split('/').pop();
  expect(sessionId).toBeTruthy();
  await expect.poll(async () => {
    const response = await page.request.get(`/api/v1/sessions/${sessionId}`);
    if (!response.ok()) return 'not-ready';
    const detail = await response.json();
    return detail.messages.at(-1)?.status;
  }).toBe('stopped');

  await page.reload();
  await expect(page.getByText(/Theo Điều 77/)).toBeVisible();
  await expect(page.getByText('Đã dừng theo yêu cầu · nội dung chưa hoàn chỉnh', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Câu trả lời hữu ích' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Tạo lại câu trả lời' })).toHaveCount(0);
});

test('durable feedback is restored after a browser reload', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Điều 77 quy định gì?');
  await input.press('Enter');

  const helpful = page.getByRole('button', { name: 'Câu trả lời hữu ích' });
  await expect(helpful).toBeVisible();
  await helpful.click();
  await expect(helpful).toHaveAttribute('title', 'Đã lưu');

  await page.reload();
  await expect(page.getByRole('button', { name: 'Câu trả lời hữu ích' })).toHaveAttribute('title', 'Đã lưu');
});

test('an unknown explicit article safe-stops without presenting unrelated sources', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Điều 999 quy định gì về EPR?');
  await input.press('Enter');

  const result = page.getByRole('region', { name: 'Kết quả xử lý' });
  await expect(result.getByText('Chưa tìm thấy điều khoản phù hợp', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ })).toHaveCount(0);
  await expect(page.getByText(/Điều 77 quy định đối tượng/)).toHaveCount(0);
});

test('real guided assessment collects dependent facts before one submit', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Kiểm tra trường hợp của doanh nghiệp' }).click();
  const form = page.getByRole('region', { name: 'Kiểm tra trường hợp của doanh nghiệp' });
  await form.getByLabel('Vai trò doanh nghiệp').selectOption('manufacturer');
  await form.getByLabel('Loại đối tượng').selectOption('commercial_packaging');
  await form.getByLabel('Nhóm sản phẩm EPR').selectOption('bao_bi');
  await form.getByLabel('Phạm vi đưa ra thị trường').selectOption('vietnam_market');
  await form.getByLabel('Mục đích sản xuất hoặc nhập khẩu').selectOption('commercial');
  await form.getByLabel('Nhóm hàng hóa được đóng gói').selectOption('thuc_pham');
  await form.getByLabel('Doanh thu bán sản phẩm liên quan mỗi năm').fill('40000000000');
  await form.getByLabel('Bao bì có được doanh nghiệp thu hồi để tái sử dụng không').selectOption('no');
  await expect(form.getByRole('button', { name: 'Kiểm tra trường hợp' })).toBeEnabled();
  await form.getByRole('button', { name: 'Kiểm tra trường hợp' }).click();

  await expect(page.getByText('Đánh giá sơ bộ', { exact: true })).toBeVisible();
  await expect(page.getByText(/Kết quả dựa trên thông tin đã cung cấp và nguồn hiển thị/)).toBeVisible();
});
