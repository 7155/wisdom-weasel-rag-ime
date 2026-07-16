import { expect, test, type Page } from '@playwright/test';
import { expectNoHorizontalPageOverflow, percentile, settleAgentTimeline } from './helpers';

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
  await expect(page.locator('.agent-inline-notice', { hasText: '图片回执不可用' })).toBeVisible();
  await expect(page.locator('.agent-sticker-block')).toBeAttached();
  await expect(page.locator('.agent-citation')).toBeAttached();
  await expect(page.locator('.agent-file-block')).toBeAttached();

  const activity = page.locator('.agent-activity');
  await expect(activity).toHaveCount(1);
  await activity.locator(':scope > summary').click();
  await expect(activity).toHaveAttribute('open', '');
  expect(await page.locator('.agent-activity-row').count()).toBeGreaterThanOrEqual(5);

  const visibleText = await page.locator('main[data-route-id="agent"]').innerText();
  expect(visibleText).not.toMatch(/\{"(?:schemaVersion|eventType|payload)"/);

  const composer = page.getByRole('textbox', { name: '消息' });
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
  await expect(roomsScene.locator('.rooms-rail')).toBeVisible();
  await expect(roomsScene.locator('.rooms-rail-empty')).toHaveText('还没有 Room');
  await expect(roomsScene.locator('.room-workspace')).toBeVisible();
  await expect(roomsScene.locator('.room-empty')).toHaveText('选择一个 Room，或新建协作 Room。');
  await expect(page.getByRole('textbox', { name: 'Room 消息' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '发送 Room 消息' })).toBeDisabled();
  await page.getByRole('button', { name: '新建 Room' }).click();
  const createRoomDialog = page.getByRole('dialog');
  await expect(createRoomDialog.getByRole('heading', { name: '新建协作 Room' })).toBeVisible();
  await expect(createRoomDialog.getByText('参与角色 3/4')).toBeVisible();
  await expect(createRoomDialog.getByRole('button', { name: '创建 Room' })).toBeDisabled();
  await expectNoHorizontalPageOverflow(page);
  await testInfo.attach(`room-scene-${testInfo.project.name}`, {
    body: await page.screenshot({ animations: 'disabled', fullPage: false }),
    contentType: 'image/png',
  });

  await page.goto('/#/roles');
  await expect(page.getByRole('region', { name: '角色列表' })).toBeVisible();
  await expect(page.locator('.persona-grid > button')).toHaveCount(3);
  const secondPersona = page.locator('.persona-grid > button').nth(1);
  const personaName = (await secondPersona.locator('strong').innerText()).trim();
  await secondPersona.click();
  await page.getByRole('button', { name: '开始对话' }).click();
  await expect(page).toHaveURL(/#\/agent\?session=session-persona-1$/);
  await expect(page.getByText(`${personaName} 对话`, { exact: true }).first()).toBeVisible();

  await page.goto('/#/roles');
  await page.getByRole('radio', { name: 'Agent 模板' }).click();
  await expect(page.getByRole('region', { name: 'Agent 模板列表' })).toBeVisible();
  await expect(page.locator('.template-list > button')).toHaveCount(3);
  await expectNoHorizontalPageOverflow(page);
});

async function openAgentScene(page: Page, projectName: string): Promise<void> {
  await page.goto('/#/agent');
  if (projectName.startsWith('mobile-')) {
    await expect(page.locator('main[data-route-id="agent"]')).toHaveAttribute(
      'data-rail-open',
      'false',
    );
    await page.getByRole('button', { name: '展开任务列表' }).click();
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
