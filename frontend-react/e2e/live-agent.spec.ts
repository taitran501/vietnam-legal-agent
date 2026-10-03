import { expect, test } from '@playwright/test';

test('React consumes the FastAPI SSE and opens source-grounded legal evidence', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Theo Điều 111 Luật Doanh nghiệp 2020, công ty cổ phần cần tối thiểu bao nhiêu cổ đông?');
  await input.press('Enter');

  await expect(page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ })).toBeVisible({ timeout: 20000 });

  await page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ }).click();
  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  const firstSource = drawer.locator('#source-1');
  await expect(
    firstSource.getByRole('heading', {
      name: 'Luật Doanh nghiệp 2020',
      exact: true,
    }),
  ).toBeVisible();
  await expect(firstSource.getByText('Số: 59/2020/QH14', { exact: true })).toBeVisible();
  await expect(firstSource).toContainText('| Điều 111');
});

test('React paints a verified answer progressively before the SSE completes', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Theo Điều 111 Luật Doanh nghiệp 2020, công ty cổ phần cần tối thiểu bao nhiêu cổ đông?');
  await input.press('Enter');

  const streamedAnswer = page.getByTestId('streaming-answer');
  await expect(streamedAnswer).toContainText('Điều 111', { timeout: 15000 });
  await expect(streamedAnswer).toBeVisible();
  await expect(page.getByRole('region', { name: 'Tiến trình xử lý' })).not.toBeVisible();
});

test('a user can stop an in-progress SSE response without losing rendered text', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Theo Điều 111 Luật Doanh nghiệp 2020, công ty cổ phần cần tối thiểu bao nhiêu cổ đông?');
  await input.press('Enter');

  await expect(page.getByTestId('streaming-answer')).toContainText('Điều 111', {
    timeout: 15000,
  });
  const stop = page.getByRole('button', { name: 'Dừng tạo câu trả lời' });
  await expect(stop).toBeVisible();
  await stop.click();

  await expect(stop).not.toBeVisible();
  await expect(page.getByTestId('streaming-answer')).not.toBeVisible();
  await expect(
    page.getByText('Đã dừng theo yêu cầu · nội dung chưa hoàn chỉnh', {
      exact: true,
    }),
  ).toBeVisible();

  const sessionId = new URL(page.url()).pathname.split('/').pop();
  expect(sessionId).toBeTruthy();
  await expect
    .poll(async () => {
      const response = await page.request.get(`/api/v1/sessions/${sessionId}`);
      if (!response.ok()) return 'not-ready';
      const detail = await response.json();
      return detail.messages.at(-1)?.status;
    })
    .toBe('stopped');

  await page.reload();
  await expect(
    page.getByText('Đã dừng theo yêu cầu · nội dung chưa hoàn chỉnh', {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Câu trả lời hữu ích' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Tạo lại câu trả lời' })).toHaveCount(0);
});

test('durable feedback is restored after a browser reload', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Điều 111 Luật Doanh nghiệp 2020 quy định gì?');
  await input.press('Enter');

  const helpful = page.getByRole('button', { name: 'Câu trả lời hữu ích' });
  // The deterministic backend streams a complete legal answer in multiple chunks.
  await expect(helpful).toBeVisible({ timeout: 20000 });
  await helpful.click();
  await expect(helpful).toHaveAttribute('title', 'Đã lưu');

  await page.reload();
  await expect(page.getByRole('button', { name: 'Câu trả lời hữu ích' })).toHaveAttribute('title', 'Đã lưu');
});

test('an unknown explicit article safe-stops without presenting unrelated sources', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Điều 999 Luật Doanh nghiệp 2020 quy định gì?');
  await input.press('Enter');

  const result = page.getByRole('region', { name: 'Kết quả xử lý' });
  await expect(result.getByText('Chưa tìm thấy điều khoản phù hợp', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ })).toHaveCount(0);
  await expect(page.getByText(/Điều 77 quy định đối tượng/)).toHaveCount(0);
});

test('case assessment starts with free text and keeps follow-up conversational', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  const prompt = 'Công ty cho tôi nghỉ việc ngay mà không báo trước. Tôi có quyền lợi gì?';
  await page.getByRole('button', { name: 'Tư vấn tình huống' }).click();
  await expect(input).toHaveValue('');
  await input.fill(prompt);

  const requestPromise = page.waitForRequest((request) => request.url().includes('/api/v1/chat') && request.method() === 'POST');
  await input.press('Enter');
  const request = await requestPromise;
  expect(request.postDataJSON().intent_hint).toBe('case_assessment');
  await expect(page.getByText(prompt, { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Câu trả lời hữu ích' })).toBeVisible({ timeout: 20000 });
  const sourceButton = page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ });
  await expect(sourceButton).toBeVisible();
  await sourceButton.click();
  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  await expect(drawer).toContainText('Bộ luật Lao động 2019');
  await expect(drawer).toContainText('Điều 36');
  await drawer.getByRole('button', { name: 'Đóng', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Kiểm tra trường hợp của doanh nghiệp' })).toHaveCount(0);

  const followUp = 'Tôi làm việc theo hợp đồng không xác định thời hạn.';
  const followUpRequestPromise = page.waitForRequest((nextRequest) => nextRequest.url().includes('/api/v1/chat') && nextRequest.method() === 'POST');
  await input.fill(followUp);
  await input.press('Enter');
  const followUpRequest = await followUpRequestPromise;
  expect(followUpRequest.postDataJSON().query).toBe(followUp);
  expect(followUpRequest.postDataJSON().intent_hint).toBe('auto');
  await expect(page.getByText(followUp, { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Câu trả lời hữu ích' })).toHaveCount(2, { timeout: 20000 });
  await expect(page.getByRole('region', { name: 'Kiểm tra trường hợp của doanh nghiệp' })).toHaveCount(0);
});

test('checklist category reaches the agent and asks through chat', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  const prompt = 'Tôi muốn đăng ký hộ kinh doanh. Cần chuẩn bị hồ sơ gì?';
  await page.getByRole('button', { name: 'Hồ sơ & thủ tục' }).click();
  await expect(input).toHaveValue('');
  await input.fill(prompt);

  const requestPromise = page.waitForRequest((request) => request.url().includes('/api/v1/chat') && request.method() === 'POST');
  await input.press('Enter');
  const request = await requestPromise;
  expect(request.postDataJSON().intent_hint).toBe('compliance_checklist');
  await expect(page.getByRole('button', { name: 'Câu trả lời hữu ích' })).toBeVisible({ timeout: 20000 });
  const sourceButton = page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ });
  await expect(sourceButton).toBeVisible();
  await sourceButton.click();
  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  await expect(drawer).toContainText('Nghị định 168/2025/NĐ-CP');
  await expect(drawer).toContainText('Điều 99');
});

test('ordinary legal questions across domains retrieve matching sources and citations', async ({ page }) => {
  test.setTimeout(240_000);
  const questions = [
    {
      article: 111,
      instrument: '59/2020/QH14',
      title: 'Luật Doanh nghiệp 2020',
      query: 'Theo Điều 111 Luật Doanh nghiệp 2020, công ty cổ phần cần tối thiểu bao nhiêu cổ đông?',
      answer: '03',
    },
    {
      article: 25,
      instrument: '45/2019/QH14',
      title: 'Bộ luật Lao động 2019',
      query: 'Điều 25 Bộ luật Lao động 2019 quy định thời gian thử việc tối đa bao lâu?',
      answer: '60 ngày',
    },
    {
      article: 4,
      instrument: '19/2023/QH15',
      title: 'Luật Bảo vệ quyền lợi người tiêu dùng 2023',
      query: 'Theo Điều 4 Luật Bảo vệ quyền lợi người tiêu dùng 19/2023/QH15, người tiêu dùng có quyền gì?',
      answer: 'an toàn tính mạng',
    },
    {
      article: 9,
      instrument: '02/2011/QH13',
      title: 'Luật Khiếu nại 2011',
      query: 'Theo Điều 9 Luật Khiếu nại 2011, thời hiệu khiếu nại là bao lâu?',
      answer: '90 ngày',
    },
    {
      article: 10,
      instrument: '104/2016/QH13',
      title: 'Luật Tiếp cận thông tin 2016',
      query: 'Theo Điều 10 Luật Tiếp cận thông tin 2016, công dân có thể yêu cầu cơ quan nào cung cấp thông tin?',
      answer: 'Yêu cầu cơ quan nhà nước cung cấp thông tin',
    },
    {
      article: 260,
      instrument: '100/2015/QH13',
      title: 'Bộ luật Hình sự 2015',
      query: 'Điều 260 Bộ luật Hình sự 2015 quy định hành vi nào liên quan đến tai nạn giao thông?',
      answer: 'Làm chết người',
    },
    {
      article: 328,
      instrument: '91/2015/QH13',
      title: 'Bộ luật Dân sự 2015',
      query: 'Điều 328 Bộ luật Dân sự 2015 quy định việc đặt cọc như thế nào?',
      answer: 'tài sản đặt cọc',
    },
    {
      article: 81,
      instrument: '52/2014/QH13',
      title: 'Luật Hôn nhân và Gia đình 2014',
      query: 'Theo Điều 81 Luật Hôn nhân và Gia đình 2014, sau ly hôn cha mẹ có trách nhiệm gì với con?',
      answer: 'trông nom, chăm sóc, nuôi dưỡng, giáo dục con',
    },
  ];

  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  const helpful = page.getByRole('button', { name: 'Câu trả lời hữu ích' });
  const sourceButtons = page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ });

  for (const [index, item] of questions.entries()) {
    await input.fill(item.query);
    await input.press('Enter');

    const completedTurns = index + 1;
    await expect(helpful).toHaveCount(completedTurns, { timeout: 30_000 });
    await expect(page.getByText(item.answer, { exact: false }).last()).toBeVisible();
    await expect(sourceButtons).toHaveCount(completedTurns);

    await sourceButtons.last().click();
    const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
    const firstSource = drawer.locator('#source-1');
    await expect(
      firstSource.getByRole('heading', {
        name: item.title,
        exact: true,
      }),
    ).toBeVisible();
    await expect(firstSource.getByText(`Số: ${item.instrument}`, { exact: true })).toBeVisible();
    await expect(firstSource).toContainText(`| Điều ${item.article}`);
    await drawer.getByRole('button', { name: 'Đóng', exact: true }).click();
  }
});
