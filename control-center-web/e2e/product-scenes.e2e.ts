import { expect, test, type Page } from '@playwright/test';
import { expectNoHorizontalPageOverflow, isMobileViewport, percentile, settleAgentTimeline } from './helpers';

// Screenshot encoding competes with the paint-latency probe on constrained CI runners.
// Keep this product fixture serial so the 50 ms responsiveness budget measures the UI itself.
test.describe.configure({ mode: 'serial' });

test('production Agent scene preserves Turn aggregation and composer responsiveness', async ({
  page,
}, testInfo) => {
  await openAgentScene(page, testInfo.project.name);

  const assistantTurns = page.locator('.agent-assistant-turn');
  expect(await assistantTurns.count()).toBeGreaterThanOrEqual(2);
  const avatarCounts = await assistantTurns.evaluateAll((turns) =>
    turns.map((turn) => turn.querySelectorAll(':scope > .agent-persona-avatar').length),
  );
  expect(avatarCounts.every((count) => count === 1)).toBe(true);

  await expect(page.locator('.agent-markdown table')).toBeAttached();
  await expect(page.locator('.agent-code-block')).toBeAttached();
  await expect(page.locator('.agent-media-block')).toHaveCount(0);
  await expect(page.locator('.agent-inline-notice', { hasText: '图片回执不可用' })).toHaveCount(0);
  await expect(page.locator('.agent-sticker-block')).toBeAttached();
  await expect(page.locator('.agent-citation')).toBeAttached();
  await expect(page.locator('.agent-file-block')).toBeAttached();
  const reasoningSummary = page.getByRole('button', { name: /查看 Agent 思考摘要/ });
  await expect(reasoningSummary).toBeVisible();
  await expect(reasoningSummary).toContainText('核对迁移计划与当前前端边界');
  await page.getByRole('button', { name: '展开 room-runtime-handoff.md' }).click();
  const filePreview = page.getByRole('region', { name: 'room-runtime-handoff.md 内联预览' });
  await expect(filePreview.getByRole('heading', { name: 'Room Runtime 交接' })).toBeVisible();
  await expect(filePreview).toContainText('文件内容按回执和摘要按需读取');
  await page.getByRole('button', { name: '收起 room-runtime-handoff.md' }).click();
  await expect(filePreview).toBeHidden();

  const activity = page.locator('.agent-activity');
  await expect(activity).toHaveCount(1);
  await activity.locator(':scope > summary').click();
  await expect(activity).toHaveAttribute('open', '');
  await expect(activity.locator('.agent-activity-row > summary strong')).toHaveText([
    '检索文档',
    '读取工具书',
    '协作 Agent',
    '权限确认',
  ]);

  const visibleText = await page.locator('main[data-route-id="agent"]').innerText();
  expect(visibleText).not.toMatch(/\{"(?:schemaVersion|eventType|payload)"/);

  const composer = page.getByRole('textbox', { name: '消息' });
  await page.waitForFunction(() => [...document.images].every((image) => image.complete));
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  await installTypingPaintProbe(page);
  const draft = 'stream paint must not block this production composer';
  await composer.pressSequentially(draft, { delay: 6 });
  await page.waitForFunction(
    (sampleCount) => {
      const samples = Reflect.get(window, '__RAG_IME_PRODUCT_TYPING__');
      return Array.isArray(samples) && samples.length >= sampleCount;
    },
    draft.length,
  );
  const samples = await page.evaluate(() =>
    Reflect.get(window, '__RAG_IME_PRODUCT_TYPING__') as number[],
  );
  const typingP95Ms = percentile(samples, 0.95);
  await testInfo.attach('product-composer-performance.json', {
    body: JSON.stringify({ samplesMs: samples, p95Ms: typingP95Ms }, null, 2),
    contentType: 'application/json',
  });
  expect(typingP95Ms).toBeLessThan(50);

  await composer.fill('/');
  await expect(page.getByRole('listbox', { name: '命令面板' })).toBeVisible();
  await composer.fill('');
  await expect(composer).toHaveAttribute('placeholder', /粘贴图片/);
  await expect(page.getByRole('button', { name: '添加附件' })).toHaveCount(0);
  await expectNoHorizontalPageOverflow(page);
});

test('production Agent scene matches the desktop and mobile visual baselines', async ({
  page,
}, testInfo) => {
  await openAgentScene(page, testInfo.project.name);
  await page.waitForFunction(() => [...document.images].every((image) => image.complete));
  await settleAgentTimeline(page);
  await page.mouse.move(1, 1);
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await expectNoHorizontalPageOverflow(page);
  await expect(page).toHaveScreenshot('agent-preview.png', {
    fullPage: false,
    mask: [page.locator('time')],
    maskColor: '#d7dee1',
  });
});

test('production Room and Role scenes retain group and persona boundaries', async ({ page }, testInfo) => {
  await page.goto('/#/rooms');
  const roomsScene = page.locator('main[data-route-id="rooms"]');
  if (isMobileViewport(page)) {
    await expect(roomsScene.locator('.rooms-rail')).toBeHidden();
    await roomsScene.getByRole('button', { name: '打开协作空间列表' }).click();
  }
  await expect(roomsScene.locator('.rooms-rail')).toBeVisible();
  await expect(roomsScene.locator('.room-workspace')).toBeVisible();
  const roomChoices = roomsScene.getByRole('button', { name: /^打开协作空间：/ });
  if (await roomChoices.count()) {
    await roomChoices.first().click();
    await expect(page.getByRole('radio', { name: '对话' })).toBeChecked();
    await page.getByRole('radio', { name: '任务' }).click();
    await expect(roomsScene.locator('.room-execution-workspace')).toBeVisible();
    const taskGraph = roomsScene.getByRole('region', { name: '任务图' });
    await expect(taskGraph).toBeVisible();
    await expect(taskGraph).toContainText('共同目标');
    await expect(taskGraph).toContainText('结果');
    await page.getByRole('radio', { name: '伙伴' }).click();
    await expect(roomsScene.locator('.room-session-workspace')).toBeVisible();
    await roomsScene.getByRole('button', { name: '查看能做什么' }).first().click();
    const boundary = page.getByRole('dialog', { name: /能做什么/ });
    await expect(boundary).toContainText('工作区托管');
    await expect(boundary).toContainText('/Volumes/work/wisdom-weasel-rag-ime');
    await expect(boundary.getByRole('radio', { name: '只读' })).toHaveCount(0);
    await expect(boundary.getByRole('button', { name: '保存权限' })).toHaveCount(0);
    await boundary.getByText(/看看可以使用哪些工具/).click();
    await expect(boundary).toContainText('Session 基础工具');
    await expect(boundary).toContainText('读取文件');
    await expect(boundary).toContainText('编辑文件');
    await expect(boundary).toContainText('写入文件');
    await expect(boundary).toContainText('运行命令');
    await expect(boundary).not.toContainText('工作区读取');
    await expect(boundary).not.toContainText('受控命令');
    await boundary.getByRole('button', { name: '知道了' }).click();
    await page.getByRole('radio', { name: '对话' }).click();
    await expect(page.getByRole('textbox', { name: '协作消息' })).toBeEnabled();
    if (isMobileViewport(page)) await roomsScene.getByRole('button', { name: '打开协作空间列表' }).click();
  } else {
    await expect(roomsScene.locator('.rooms-rail-empty')).toHaveText('还没有协作空间');
    const roomEmptyState = roomsScene.locator('.ui-empty-state');
    await expect(roomEmptyState).toContainText('选择一个协作空间');
    await expect(roomEmptyState.locator('img')).toHaveCount(0);
    await expect(page.getByRole('textbox', { name: '协作消息' })).toBeDisabled();
    await expect(page.getByRole('button', { name: '发送消息' })).toBeDisabled();
  }
  await page.getByRole('button', { name: '开始新的协作' }).click();
  const createRoomDialog = page.getByRole('dialog');
  await expect(createRoomDialog.getByRole('heading', { name: '开始一起做事' })).toBeVisible();
  await expect(createRoomDialog.getByText(/至少 2 位 · \d\/4/)).toBeVisible();
  await expect(createRoomDialog.getByRole('button', { name: '开始协作' })).toBeDisabled();
  await expectNoHorizontalPageOverflow(page);
  await testInfo.attach(`room-scene-${testInfo.project.name}`, {
    body: await page.screenshot({ animations: 'disabled', fullPage: false }),
    contentType: 'image/png',
  });

  await page.goto('/#/roles');
  await expect(page.locator('#workspace-main').getByRole('heading', { name: '伙伴', level: 1 })).toBeVisible();
  await expect(page.getByRole('region', { name: '伙伴目录' })).toBeVisible();
  expect(await page.locator('.persona-grid > button').count()).toBeGreaterThanOrEqual(3);
  const secondPersona = page.locator('.persona-grid > button').nth(1);
  const personaName = (await secondPersona.locator('strong').innerText()).trim();
  await secondPersona.click();
  await page.getByRole('button', { name: '开始对话' }).click();
  await expect(page).toHaveURL(/#\/agent\?session=session-persona-1$/);
  await expect(page.getByText(`${personaName} 对话`, { exact: true }).first()).toBeVisible();

  await page.goto('/#/roles');
  await expect(page.getByRole('region', { name: '伙伴能力边界' })).toBeVisible();
  await expect(page.getByText('新对话设置', { exact: true })).toBeVisible();
  await expect(page.getByRole('radio', { name: 'Agent 模板' })).toHaveCount(0);
  await expect(page.getByRole('radio', { name: /主持人|执行者|研究员|审查员/ })).toHaveCount(0);
  await expectNoHorizontalPageOverflow(page);
});

async function openAgentScene(page: Page, projectName: string): Promise<void> {
  await page.goto('/#/agent');
  if (projectName.startsWith('mobile-')) {
    await expect(page.locator('main[data-route-id="agent"]')).toHaveAttribute(
      'data-rail-open',
      'false',
    );
    await page.getByRole('button', { name: '展开对话列表' }).click();
    await expect(page.locator('main[data-route-id="agent"]')).toHaveAttribute(
      'data-rail-open',
      'true',
    );
    await expect(page.locator('.agent-session-row').first()).toBeVisible();
    await page.locator('.agent-session-row').first().click();
    await expect(page.locator('main[data-route-id="agent"]')).toHaveAttribute(
      'data-rail-open',
      'false',
    );
  } else {
    await expect(page.locator('.agent-session-row').first()).toBeVisible();
  }
  await expect(page.locator('.agent-turn').first()).toBeVisible();
}

async function installTypingPaintProbe(page: Page): Promise<void> {
  await page.evaluate(() => {
    const composer = document.querySelector<HTMLTextAreaElement>('.agent-composer textarea');
    if (!composer) throw new Error('Agent composer is unavailable');
    const samples: number[] = [];
    Reflect.set(window, '__RAG_IME_PRODUCT_TYPING__', samples);
    composer.addEventListener('input', () => {
      const started = performance.now();
      requestAnimationFrame(() => samples.push(performance.now() - started));
    });
  });
}
