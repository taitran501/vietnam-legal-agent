import { expect, test } from '@playwright/test';

test('React consumes the real FastAPI SSE and opens verified legal evidence', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('EPR về bao bì được quy định như thế nào?');
  await input.press('Enter');

  await expect(
    page.getByText(/Theo Điều 77.*nhà sản xuất và nhập khẩu phải đối chiếu trách nhiệm tái chế/)
  ).toBeVisible();
  await expect(page.getByRole('button', { name: /Đã hoàn tất \d+ bước/ })).toBeVisible();

  await page.getByRole('button', { name: 'Xem 1 nguồn tham khảo' }).click();
  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  await expect(drawer.getByText('Nghị định 08/2022/NĐ-CP')).toBeVisible();
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
  await expect(page.getByRole('button', { name: /Đã hoàn tất \d+ bước/ })).toBeVisible();
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
});

test('real multi-turn case waits for facts and resumes without using web search', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Tôi là nhà sản xuất, có phải thực hiện EPR không?');
  await input.press('Enter');

  const firstResult = page.getByRole('region', { name: 'Kết quả workflow' });
  await expect(firstResult.getByText('Cần thêm thông tin để tiếp tục')).toBeVisible();
  await expect(page.getByText(/loại sản phẩm hoặc bao bì/)).toBeVisible();

  await input.fill('Sản phẩm là bao bì, vật liệu nhựa, hoạt động tại thị trường Việt Nam.');
  await input.press('Enter');

  await expect(page.getByText('Đánh giá sơ bộ', { exact: true })).toBeVisible();
  await expect(
    page.getByText(/Kết quả dựa trên thông tin đã cung cấp và các nguồn hiển thị/)
  ).toBeVisible();
  await expect(page.getByText(/nguồn web/i)).not.toBeVisible();
});
