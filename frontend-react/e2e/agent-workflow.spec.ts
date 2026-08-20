import { expect, test, type Page } from '@playwright/test';

async function mockBaseApi(page: Page, options: { caseWorkflowReady?: boolean } = {}) {
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
        case_workflow: options.caseWorkflowReady === false
          ? { status: 'blocked', reason: 'corpus_not_ready' }
          : { status: 'ready', reason: 'preview_unapproved_corpus' },
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

test('guided assessment resolves dependent fields and submits one chat turn', async ({ page }) => {
  await mockBaseApi(page);
  let chatCalls = 0;
  let resolveCalls = 0;
  await page.route('**/api/v1/case-form/resolve', async (route) => {
    resolveCalls += 1;
    const body = route.request().postDataJSON() as { fact_updates?: Record<string, { value?: string }> };
    const updates = body.fact_updates || {};
    const facts: Record<string, string> = {};
    const validation_errors: Record<string, string> = {};
    for (const [key, update] of Object.entries(updates)) {
      const value = String(update?.value || '').trim();
      if (!value) continue;
      if (key === 'annual_revenue_vnd' && (!/^\d+$/.test(value) || Number(value) > 1_000_000_000_000_000)) {
        validation_errors[key] = 'Doanh thu phải là số nguyên không âm, tính bằng VNĐ.';
        continue;
      }
      if (key === 'recovery_rate' && (!/^\d+(\.\d+)?$/.test(value) || Number(value) < 0 || Number(value) > 100)) {
        validation_errors[key] = 'Tỷ lệ thu hồi phải nằm trong khoảng 0–100.';
        continue;
      }
      facts[key] = value;
    }
    const fieldDefinitions = [
      ['business_role', 'Vai trò doanh nghiệp', 'select', true],
      ['object_kind', 'Loại đối tượng', 'select', true],
      ['product_group', 'Nhóm sản phẩm EPR', 'select', true],
      ['market_placement', 'Phạm vi đưa ra thị trường', 'select', true],
      ['activity_purpose', 'Mục đích sản xuất hoặc nhập khẩu', 'select', true],
      ...(facts.product_group === 'bao_bi' ? [['packaged_goods_category', 'Nhóm hàng hóa được đóng gói', 'select', true]] : []),
      ...(facts.product_group === 'bao_bi' && facts.market_placement === 'vietnam_market'
        ? [['annual_revenue_vnd', 'Doanh thu bán sản phẩm liên quan mỗi năm', 'number', true], ['reused_by_producer', 'Bao bì có được doanh nghiệp thu hồi để tái sử dụng không', 'select', true]]
        : []),
      ...(facts.reused_by_producer === 'yes' ? [['recovery_rate', 'Tỷ lệ thu hồi và tái sử dụng', 'number', true]] : []),
    ];
    const options: Record<string, Array<{ value: string; label: string }>> = {
      business_role: [{ value: 'manufacturer', label: 'Nhà sản xuất' }],
      object_kind: [{ value: 'commercial_packaging', label: 'Bao bì thương phẩm' }],
      product_group: [{ value: 'bao_bi', label: 'Bao bì' }],
      market_placement: [{ value: 'vietnam_market', label: 'Đưa ra thị trường Việt Nam' }],
      activity_purpose: [{ value: 'commercial', label: 'Kinh doanh thương mại' }],
      packaged_goods_category: [{ value: 'thuc_pham', label: 'Thực phẩm' }],
      reused_by_producer: [{ value: 'yes', label: 'Có' }, { value: 'no', label: 'Không' }],
    };
    const fields = fieldDefinitions.map(([key, label, kind, required], display_order) => ({
      key, label, kind, required, display_order, group: 'Thông tin cần cung cấp', importance: required ? 'required' : 'informational',
      missing: !facts[key as string] || Boolean(validation_errors[key as string]), value: facts[key as string] || '', options: options[key as string] || [], help_text: 'Thông tin này giúp chọn đúng quy định cần đối chiếu.',
    }));
    const missing_facts = fields.filter((field) => field.required && field.missing).map((field) => field.key);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        form_version: 'case-form-v1', task_type: body.task_type || 'assess_epr_obligation', status: missing_facts.length || Object.keys(validation_errors).length ? 'collecting' : 'ready',
        facts, fields, missing_facts, validation_errors, completed_count: fields.filter((field) => field.required && !field.missing).length, required_count: fields.filter((field) => field.required).length,
      }),
    });
  });
  await page.route('**/api/v1/chat', (route) => {
    chatCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        { type: 'status', stage: 'turn_started', turn_id: 'turn-1', user_message_id: 1, assistant_message_id: 2, turn_status: 'streaming' },
        { type: 'response_chunk', chunk: 'Đã kiểm tra thông tin doanh nghiệp.' },
        {
          type: 'response_complete',
          text: 'Đã kiểm tra thông tin doanh nghiệp.',
          documents: [], source: 'legal', task_type: 'assess_epr_obligation', citations: [], outcome: 'completed', result_type: 'assessment',
          assessment: { status: 'likely_in_scope', conclusion: 'Trường hợp có khả năng thuộc phạm vi cần thực hiện EPR.', reasons: [], next_steps: ['Đối chiếu hồ sơ liên quan.'] },
          assistant_message_id: 2,
        },
      ]),
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Kiểm tra trường hợp của doanh nghiệp' }).click();
  const form = page.getByRole('region', { name: 'Kiểm tra trường hợp của doanh nghiệp' });
  await expect(form).toBeVisible();
  expect(chatCalls).toBe(0);
  await form.getByLabel('Vai trò doanh nghiệp').selectOption('manufacturer');
  await form.getByLabel('Loại đối tượng').selectOption('commercial_packaging');
  await form.getByLabel('Nhóm sản phẩm EPR').selectOption('bao_bi');
  await form.getByLabel('Phạm vi đưa ra thị trường').selectOption('vietnam_market');
  await form.getByLabel('Mục đích sản xuất hoặc nhập khẩu').selectOption('commercial');
  await expect(form.getByText('Còn thiếu 3 thông tin')).toBeVisible();
  await expect(form.getByLabel('Nhóm hàng hóa được đóng gói')).toBeVisible();
  await form.getByLabel('Nhóm hàng hóa được đóng gói').selectOption('thuc_pham');
  await form.getByLabel('Doanh thu bán sản phẩm liên quan mỗi năm').fill('29999999999.5');
  await expect(form.getByText('Doanh thu phải là số nguyên không âm, tính bằng VNĐ.')).toBeVisible();
  await expect(form.getByRole('button', { name: 'Kiểm tra trường hợp' })).toBeDisabled();
  await form.getByLabel('Doanh thu bán sản phẩm liên quan mỗi năm').fill('40000000000');
  await form.getByLabel('Bao bì có được doanh nghiệp thu hồi để tái sử dụng không').selectOption('no');
  await expect(form.getByRole('button', { name: 'Kiểm tra trường hợp' })).toBeEnabled();
  await form.getByRole('button', { name: 'Kiểm tra trường hợp' }).click();

  await expect(page).toHaveURL(/\/conversations\//);
  await expect(page.getByText('Đánh giá sơ bộ', { exact: true })).toBeVisible();
  await expect(page.getByText('Đã kiểm tra thông tin doanh nghiệp.', { exact: true })).toBeVisible();
  await expect(page.getByText('Hãy kiểm tra trường hợp của doanh nghiệp dựa trên thông tin tôi đã cung cấp.', { exact: true })).toHaveCount(1);
  expect(chatCalls).toBe(1);
  expect(resolveCalls).toBeGreaterThan(1);
  await captureReview(page, 'guided-assessment-completed');
});

test('guided checklist keeps the checklist prompt and history title', async ({ page }) => {
  await mockBaseApi(page);
  let chatQuery = '';
  let persistedSessionId = '';
  await page.route('**/api/v1/case-form/resolve', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      form_version: 'case-form-v1',
      task_type: 'build_compliance_checklist',
      status: 'ready',
      facts: {},
      fields: [],
      missing_facts: [],
      validation_errors: {},
      completed_count: 0,
      required_count: 0,
    }),
  }));
  await page.route('**/api/v1/chat', async (route) => {
    const body = route.request().postDataJSON() as { query?: string; conversation_id?: string };
    chatQuery = String(body.query || '');
    persistedSessionId = String(body.conversation_id || '');
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        { type: 'status', stage: 'turn_started', turn_id: 'checklist-turn', user_message_id: 21, assistant_message_id: 22, turn_status: 'streaming' },
        {
          type: 'response_complete',
          text: 'Dưới đây là danh sách việc cần làm.',
          source: 'legal',
          task_type: 'build_compliance_checklist',
          result_type: 'checklist',
          outcome: 'completed',
          checklist: [{ item: 'Đối chiếu căn cứ EPR' }],
          documents: [],
          citations: [],
          assistant_message_id: 22,
        },
      ]),
    });
  });
  const persistedSession = () => persistedSessionId ? [{
    id: persistedSessionId,
    title: 'Hãy tạo danh sách việc cần làm cho doanh nghiệp dựa trên thông tin tôi đã cung cấp.',
    created_at: 0,
    updated_at: 0,
    message_count: 2,
  }] : [];
  await page.route('**/api/v1/sessions?*', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(persistedSession()),
  }));
  await page.route('**/api/v1/sessions', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(persistedSession()),
  }));
  await page.route('**/api/v1/sessions/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/case')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: 'null' });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'checklist-session',
        title: 'Hãy tạo danh sách việc cần làm cho doanh nghiệp dựa trên thông tin tôi đã cung cấp.',
        created_at: 0,
        updated_at: 0,
        message_count: 2,
        messages: [
          { id: 21, role: 'user', content: 'Hãy tạo danh sách việc cần làm cho doanh nghiệp dựa trên thông tin tôi đã cung cấp.', timestamp: '2026-08-14T00:00:00Z', status: 'complete', metadata: {} },
          { id: 22, role: 'assistant', content: 'Dưới đây là danh sách việc cần làm.', timestamp: '2026-08-14T00:00:01Z', status: 'complete', metadata: { task_type: 'build_compliance_checklist', result_type: 'checklist', outcome: 'completed', checklist: [{ item: 'Đối chiếu căn cứ EPR' }] } },
        ],
      }),
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Tạo danh sách việc cần làm' }).click();
  const form = page.getByRole('region', { name: 'Tạo danh sách việc cần làm' });
  await form.getByRole('button', { name: 'Tạo danh sách việc cần làm' }).click();

  await expect(page.getByText('Danh sách việc cần làm', { exact: true })).toBeVisible();
  await expect(page.getByText('Hãy tạo danh sách việc cần làm cho doanh nghiệp dựa trên thông tin tôi đã cung cấp.', { exact: true })).toHaveCount(1);
  await expect(page.getByText(/Hãy kiểm tra trường hợp của doanh nghiệp/)).toHaveCount(0);
  await expect.poll(() => chatQuery).toBe('Hãy tạo danh sách việc cần làm cho doanh nghiệp dựa trên thông tin tôi đã cung cấp.');
  await expect(page.locator('aside').getByTitle('Hãy tạo danh sách việc cần làm cho doanh nghiệp dựa trên thông tin tôi đã cung cấp.')).toBeVisible();
  await page.reload();
  await expect(page.getByText('Danh sách việc cần làm', { exact: true })).toBeVisible();
  await expect(page.locator('aside').getByTitle('Hãy tạo danh sách việc cần làm cho doanh nghiệp dựa trên thông tin tôi đã cung cấp.')).toBeVisible();
});

test('guided drafts ask before discard and new conversation clears the form', async ({ page }) => {
  await mockBaseApi(page);
  await page.route('**/api/v1/case-form/resolve', async (route) => {
    const body = route.request().postDataJSON() as { fact_updates?: Record<string, { value?: string }> };
    const value = String(body.fact_updates?.business_role?.value || '');
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        form_version: 'case-form-v1',
        task_type: 'assess_epr_obligation',
        status: value ? 'ready' : 'collecting',
        facts: value ? { business_role: { value, source: 'case_panel', confirmation_status: 'user_confirmed' } } : {},
        fields: [{ key: 'business_role', label: 'Vai trò doanh nghiệp', kind: 'select', options: [{ value: 'manufacturer', label: 'Nhà sản xuất' }], required: true, importance: 'required', missing: !value, value, help_text: 'Chọn vai trò.' }],
        missing_facts: value ? [] : ['business_role'],
        validation_errors: {},
        completed_count: value ? 1 : 0,
        required_count: 1,
      }),
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Kiểm tra trường hợp của doanh nghiệp' }).click();
  const form = page.getByRole('region', { name: 'Kiểm tra trường hợp của doanh nghiệp' });
  await form.getByLabel('Vai trò doanh nghiệp').selectOption('manufacturer');
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('Bỏ các thông tin chưa gửi');
    await dialog.dismiss();
  });
  await page.getByRole('button', { name: 'Quay lại tra cứu quy định' }).click();
  await expect(form).toBeVisible();

  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Cuộc trò chuyện mới' }).click();
  await expect(form).not.toBeVisible();
  await expect(page.getByLabel('Câu hỏi pháp lý')).toBeVisible();
});

test('case capability explains why its action is unavailable on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockBaseApi(page, { caseWorkflowReady: false });
  await page.goto('/');

  const action = page.getByRole('button', { name: 'Kiểm tra trường hợp của doanh nghiệp' });
  await expect(action).toBeDisabled();
  await expect(page.getByText('Chức năng này đang tạm khóa vì dữ liệu pháp luật đang được kiểm tra.')).toBeVisible();
  await expect(action).toHaveAttribute('aria-describedby', 'case-capability-message');
});

test('invalid conversation URL is treated as a real not-found route', async ({ page }) => {
  await mockBaseApi(page);
  await page.goto('/conversations/not-a-real-conversation');

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText('Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.')).toBeVisible();
  await expect(page.locator('aside').getByTitle('Cuộc trò chuyện')).toHaveCount(0);
});

test('guided submit failure keeps the draft available for another attempt', async ({ page }) => {
  await mockBaseApi(page);
  let chatCalls = 0;
  await page.route('**/api/v1/case-form/resolve', async (route) => {
    const body = route.request().postDataJSON() as { task_type?: string; fact_updates?: Record<string, { value?: string }> };
    const updates = body.fact_updates || {};
    const definitions = [
      ['business_role', 'Vai trò doanh nghiệp'],
      ['object_kind', 'Loại đối tượng'],
      ['product_group', 'Nhóm sản phẩm EPR'],
      ['market_placement', 'Phạm vi đưa ra thị trường'],
      ['activity_purpose', 'Mục đích sản xuất hoặc nhập khẩu'],
    ];
    const options: Record<string, Array<{ value: string; label: string }>> = {
      business_role: [{ value: 'manufacturer', label: 'Nhà sản xuất' }],
      object_kind: [{ value: 'product', label: 'Sản phẩm' }],
      product_group: [{ value: 'pin', label: 'Pin' }],
      market_placement: [{ value: 'vietnam_market', label: 'Đưa ra thị trường Việt Nam' }],
      activity_purpose: [{ value: 'commercial', label: 'Kinh doanh thương mại' }],
    };
    const fields = definitions.map(([key, label], display_order) => ({
      key, label, kind: 'select', options: options[key] || [], required: true, importance: 'required', display_order,
      missing: !updates[key]?.value, value: updates[key]?.value || '', help_text: 'Thông tin này giúp chọn đúng quy định cần đối chiếu.',
    }));
    const missing_facts = fields.filter((field) => field.missing).map((field) => field.key);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        form_version: 'case-form-v1', task_type: body.task_type || 'assess_epr_obligation',
        status: missing_facts.length ? 'collecting' : 'ready',
        facts: Object.fromEntries(Object.entries(updates).filter(([, update]) => update.value).map(([key, update]) => [key, { value: update.value, source: 'case_panel', confirmation_status: 'user_confirmed' }])),
        fields, missing_facts, validation_errors: {}, completed_count: fields.length - missing_facts.length, required_count: fields.length,
      }),
    });
  });
  await page.route('**/api/v1/chat', async (route) => {
    chatCalls += 1;
    if (chatCalls === 1) {
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: eventStream([
          { type: 'status', stage: 'turn_started', turn_id: 'failed-turn', user_message_id: 11, assistant_message_id: 12, turn_status: 'streaming' },
          { type: 'error', code: 'pipeline_unavailable', message: 'Dịch vụ tạm thời không khả dụng.', retryable: true, retry_after_seconds: 0 },
        ]),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: eventStream([
        { type: 'status', stage: 'turn_started', turn_id: 'recovered-turn', user_message_id: 13, assistant_message_id: 14, turn_status: 'streaming' },
        { type: 'response_complete', text: 'Đã xử lý lại thông tin.', source: 'legal', documents: [], citations: [], assistant_message_id: 14, outcome: 'completed', result_type: 'assessment', assessment: { status: 'likely_in_scope', conclusion: 'Có khả năng thuộc phạm vi EPR.' } },
      ]),
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Kiểm tra trường hợp của doanh nghiệp' }).click();
  const form = page.getByRole('region', { name: 'Kiểm tra trường hợp của doanh nghiệp' });
  await form.getByLabel('Vai trò doanh nghiệp').selectOption('manufacturer');
  await form.getByLabel('Loại đối tượng').selectOption('product');
  await form.getByLabel('Nhóm sản phẩm EPR').selectOption('pin');
  await form.getByLabel('Phạm vi đưa ra thị trường').selectOption('vietnam_market');
  await form.getByLabel('Mục đích sản xuất hoặc nhập khẩu').selectOption('commercial');
  await form.getByRole('button', { name: 'Kiểm tra trường hợp' }).click();

  await expect(page.getByText('Dịch vụ trả lời đang bận')).toBeVisible();
  const recoveryForm = page.getByRole('region', { name: 'Kiểm tra trường hợp của doanh nghiệp' });
  await expect(recoveryForm.getByLabel('Vai trò doanh nghiệp')).toHaveValue('manufacturer');
  await recoveryForm.getByRole('button', { name: 'Kiểm tra trường hợp' }).click();
  await expect(page.getByText('Đã xử lý lại thông tin.', { exact: true })).toBeVisible();
  expect(chatCalls).toBe(2);
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
  await page.getByRole('button', { name: 'Kiểm tra tính hợp pháp & Nghĩa vụ' }).click();
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
        { type: 'status', stage: 'turn_started', turn_id: 'missing-turn', user_message_id: 31, assistant_message_id: 32, turn_status: 'streaming' },
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
  await page.getByRole('button', { name: 'Kiểm tra tính hợp pháp & Nghĩa vụ' }).click();
  await page.getByLabel('Câu hỏi pháp lý').fill('Hãy kiểm tra căn cứ pháp lý cho tình huống này.');
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();

  const result = page.getByRole('region', { name: 'Kết quả xử lý' });
  await expect(result.getByText('Chưa đủ căn cứ để trả lời chắc chắn')).toBeVisible();
  await expect(result.getByRole('button', { name: 'Tìm nguồn công khai' })).toHaveCount(0);
  await expect(result.getByText(/Thông tin được cập nhật đến/)).toHaveCount(0);
  await expect(page.getByText(/Bản thử nghiệm:/)).toHaveCount(1);
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
          preview: true,
        },
      ]),
    })
  );

  await page.goto('/');
  await page.getByRole('button', { name: 'Kiểm tra tính hợp pháp & Nghĩa vụ' }).click();
  await page.getByLabel('Câu hỏi pháp lý').fill('Điều 77 Nghị định 08/2022 quy định gì?');
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click();
  await captureReview(page, 'integrated-completed-answer');
  await page.getByRole('link', { name: '[1]' }).click();

  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  await expect(drawer.getByText(/Bản thử nghiệm:/)).toBeVisible();
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
  await drawer.getByRole('button', { name: 'Lưu và tiếp tục tạo danh sách việc cần làm' }).click();

  await expect(drawer).not.toBeVisible();
  await expect(page.getByText('Danh sách việc cần làm', { exact: true })).toBeVisible();
  expect(patchBody?.task_type).toBe('build_compliance_checklist');
  expect(continuationBody?.operation).toBe('continue_case');
  expect(continuationBody?.intent_hint).toBe('compliance_checklist');
  expect(continuationBody?.query).toBe('Hãy tạo danh sách việc cần làm cho doanh nghiệp dựa trên thông tin tôi đã cung cấp.');
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
  await page.route('**/api/v1/sessions*', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{ id: 'history-still-works', title: 'Lịch sử vẫn dùng được', created_at: 1, message_count: 2 }]),
  }));
  await page.goto('/');
  await expect(page.getByText('Lịch sử vẫn dùng được')).toBeVisible();
  await expect(page.getByText(/Văn bản pháp luật chưa được kiểm tra nên kết luận pháp lý đang tạm khóa/)).toBeVisible();
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
  await expect(page.getByText('Nguồn chính thức bên ngoài kho văn bản', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: '[1]' }).click();
  const drawer = page.getByRole('dialog', { name: 'Nguồn tham khảo' });
  const outbound = drawer.getByRole('link', { name: 'Mở nguồn' });
  await expect(outbound).toHaveAttribute('href', 'https://vanban.chinhphu.vn/?docid=216867');
  await expect(drawer.getByText(/example\.com/)).toHaveCount(0);
});
