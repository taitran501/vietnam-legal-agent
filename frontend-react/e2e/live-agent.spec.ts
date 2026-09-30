import { expect, test } from '@playwright/test';

test('React consumes the real FastAPI SSE and opens verified legal evidence', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Điều 77 Nghị định 08/2022 quy định gì về trách nhiệm tái chế bao bì?');
  await input.press('Enter');

  await expect(page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ })).toBeVisible({ timeout: 20000 });

  await page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ }).click();
  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  const firstSource = drawer.locator('#source-1');
  await expect(
    firstSource.getByRole('heading', {
      name: 'Nghị định 08/2022/NĐ-CP',
      exact: true,
    }),
  ).toBeVisible();
  await expect(firstSource.getByText('Số: 08/2022/NĐ-CP', { exact: true })).toBeVisible();
  await expect(firstSource).toContainText('| Điều 77');
});

test('React paints a verified answer progressively before the SSE completes', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Điều 77 Nghị định 08/2022 quy định gì về trách nhiệm tái chế bao bì?');
  await input.press('Enter');

  const streamedAnswer = page.getByTestId('streaming-answer');
  await expect(streamedAnswer).toContainText('Điều 77', { timeout: 15000 });
  await expect(streamedAnswer).toBeVisible();
  await expect(page.getByRole('region', { name: 'Tiến trình xử lý' })).not.toBeVisible();
});

test('a user can stop an in-progress SSE response without losing rendered text', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  await input.fill('Điều 77 Nghị định 08/2022 quy định gì về trách nhiệm tái chế bao bì?');
  await input.press('Enter');

  await expect(page.getByTestId('streaming-answer')).toContainText('Điều 77', {
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
  await input.fill('Điều 77 quy định gì?');
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
  await input.fill('Điều 999 quy định gì về EPR?');
  await input.press('Enter');

  const result = page.getByRole('region', { name: 'Kết quả xử lý' });
  await expect(result.getByText('Chưa tìm thấy điều khoản phù hợp', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ })).toHaveCount(0);
  await expect(page.getByText(/Điều 77 quy định đối tượng/)).toHaveCount(0);
});

test('case assessment starts with free text instead of a long intake form', async ({ page }) => {
  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  const prompt = 'Tôi sản xuất bao bì nhựa và bán tại Việt Nam. Có phải thực hiện EPR không?';
  await page.getByRole('button', { name: 'Tư vấn tình huống' }).click();
  await expect(input).toHaveValue('');
  await input.fill(prompt);

  const requestPromise = page.waitForRequest((request) => request.url().includes('/api/v1/chat') && request.method() === 'POST');
  await input.press('Enter');
  const request = await requestPromise;
  expect(request.postDataJSON().intent_hint).toBe('case_assessment');
  await expect(page.getByText(prompt, { exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Kết quả xử lý' })).toBeVisible({ timeout: 20000 });
  await expect(page.getByText(/Trước hết, bạn cho biết/)).toBeVisible();
  await expect(page.getByRole('region', { name: 'Kiểm tra trường hợp của doanh nghiệp' })).toHaveCount(0);

  const followUp = 'Tôi là nhà sản xuất, kinh doanh thương mại, doanh thu khoảng 40 tỷ đồng mỗi năm và không thu hồi bao bì.';
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
  await expect(page.getByRole('region', { name: 'Kết quả xử lý' })).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole('region', { name: 'Kiểm tra trường hợp của doanh nghiệp' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Câu trả lời hữu ích' })).toBeVisible();
});

test('ordinary EPR questions retrieve canonical articles and render cited answers in chat', async ({ page }) => {
  test.setTimeout(240_000);
  const questions = [
    {
      article: 77,
      query: 'Nhà sản xuất, nhập khẩu phải tái chế sản phẩm, bao bì đưa ra thị trường Việt Nam?',
      answer: 'trách nhiệm tái chế sản phẩm, bao bì',
    },
    {
      article: 78,
      query: 'Tỷ lệ tái chế bắt buộc là tỷ lệ bao nhiêu trên tổng khối lượng sản phẩm, bao bì trong năm có trách nhiệm?',
      answer: 'tỷ lệ khối lượng sản phẩm, bao bì tối thiểu',
    },
    {
      article: 79,
      query: 'Tôi có thể tự tái chế hay thuê đơn vị khác để thực hiện trách nhiệm tái chế?',
      answer: 'Thuê đơn vị tái chế để thực hiện tái chế',
    },
    {
      article: 80,
      query: 'Khi nào nhà sản xuất, nhập khẩu phải đăng ký kế hoạch tái chế và báo cáo kết quả?',
      answer: 'Trước ngày 31 tháng 3 hằng năm',
    },
    {
      article: 81,
      query: 'Công thức F = R x V x Fs dùng để tính khoản đóng góp tài chính như thế nào?',
      answer: 'F = R x V x Fs',
    },
    {
      article: 82,
      query: 'Tiền đóng góp tài chính vào Quỹ được dùng hỗ trợ phân loại, thu gom, vận chuyển và tái chế sản phẩm bao bì nào?',
      answer: 'hỗ trợ các hoạt động phân loại, thu gom, vận chuyển, tái chế',
    },
    {
      article: 83,
      query: 'Nhà sản xuất, nhập khẩu có doanh thu dưới 30 tỷ đồng/năm có được miễn đóng góp hỗ trợ xử lý chất thải không?',
      answer: 'dưới 30 tỷ đồng/năm',
    },
    {
      article: 84,
      query: 'Trước hạn nào phải kê khai và nộp đủ tiền đóng góp hỗ trợ xử lý chất thải?',
      answer: 'Trước ngày 20 tháng 4 hằng năm',
    },
    {
      article: 85,
      query: 'Quỹ phải công khai việc tiếp nhận và sử dụng tiền đóng góp hỗ trợ xử lý chất thải ra sao?',
      answer: 'công khai, minh bạch, đúng mục đích',
    },
    {
      article: 86,
      query: 'Nhà sản xuất, nhập khẩu phải công khai những thông tin gì về sản phẩm, bao bì?',
      answer: 'Thành phần nguyên liệu, nhiên liệu, vật liệu',
    },
  ];

  await page.goto('/');
  const input = page.getByLabel('Câu hỏi pháp lý');
  const helpful = page.getByRole('button', { name: 'Câu trả lời hữu ích' });
  const sourceButtons = page.getByRole('button', { name: /Xem \d+ nguồn tham khảo/ });
  const caveat = 'Lưu ý: Câu trả lời tóm tắt nội dung trong nguồn được trích dẫn; dữ liệu hiện chưa xác nhận các cập nhật hoặc hiệu lực hiện hành.';

  for (const [index, item] of questions.entries()) {
    await input.fill(item.query);
    await input.press('Enter');

    const completedTurns = index + 1;
    await expect(helpful).toHaveCount(completedTurns, { timeout: 30_000 });
    await expect(page.getByText(item.answer, { exact: false }).last()).toBeVisible();
    await expect(page.getByText(caveat, { exact: false }).last()).toBeVisible();
    await expect(sourceButtons).toHaveCount(completedTurns);

    await sourceButtons.last().click();
    const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
    const firstSource = drawer.locator('#source-1');
    await expect(
      firstSource.getByRole('heading', {
        name: 'Nghị định 08/2022/NĐ-CP',
        exact: true,
      }),
    ).toBeVisible();
    await expect(firstSource).toContainText(`| Điều ${item.article}`);
    await drawer.getByRole('button', { name: 'Đóng', exact: true }).click();
  }
});
