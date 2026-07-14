import { expect, test, type Page } from '@playwright/test';
import { expectNoHorizontalPageOverflow, percentile } from './helpers';

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
  await expect(page.locator('.agent-media-block')).toBeAttached();
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
  await page.getByRole('button', { name: '添加附件' }).click();
  await expect(page.locator('.agent-composer__attachments')).toContainText(
    'agent-runtime-trace.txt',
  );
  await expectNoHorizontalPageOverflow(page);
});

test('production Agent scene matches the desktop and mobile visual baselines', async ({
  page,
}, testInfo) => {
  await openAgentScene(page, testInfo.project.name);
  await page.waitForFunction(() => [...document.images].every((image) => image.complete));
  await expectNoHorizontalPageOverflow(page);
  await expect(page).toHaveScreenshot('agent-preview.png', {
    fullPage: false,
    mask: [page.locator('time')],
    maskColor: '#d7dee1',
  });
});

test('production Room and Role scenes retain group and persona boundaries', async ({ page }, testInfo) => {
  await page.goto('/#/rooms');
  await expect(page.locator('.room-turn')).toBeVisible();
  await expect(page.locator('.room-participants > span')).toHaveCount(2);
  await expect(page.locator('.room-participant-message')).toHaveCount(2);
  const group = page.locator('.room-group-activity');
  await expect(group).toBeVisible();
  await group.locator(':scope > summary').click();
  await expect(group).toHaveAttribute('open', '');
  await expect(group.locator(':scope > div > p')).toHaveCount(3);
  const groupAvatarBoxes = await group
    .locator(':scope > div .agent-persona-avatar')
    .evaluateAll((avatars) => avatars.map((avatar) => {
      const bounds = avatar.getBoundingClientRect();
      return { width: bounds.width, height: bounds.height };
    }));
  expect(groupAvatarBoxes).toHaveLength(3);
  for (const box of groupAvatarBoxes) {
    expect(Math.abs(box.width - box.height)).toBeLessThanOrEqual(1);
    expect(box.width).toBeLessThanOrEqual(32);
  }
  await page.getByRole('textbox', { name: 'Room 消息' }).fill('请主持人汇总两个分支。');
  await expect(page.getByRole('button', { name: '发送 Room 消息' })).toBeEnabled();
  await expectNoHorizontalPageOverflow(page);
  await testInfo.attach(`room-scene-${testInfo.project.name}`, {
    body: await page.screenshot({ animations: 'disabled', fullPage: false }),
    contentType: 'image/png',
  });

  await page.goto('/#/roles');
  await expect(page.getByRole('region', { name: 'Persona 列表' })).toBeVisible();
  await expect(page.locator('.persona-grid > button')).toHaveCount(3);
  await page.getByRole('radio', { name: 'Agent Template' }).click();
  await expect(page.getByRole('region', { name: 'Agent Template 列表' })).toBeVisible();
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
    await page.getByRole('button', { name: '展开 Sessions' }).click();
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
