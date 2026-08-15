import { expect, test } from '@playwright/test';

test('model changes close immediately and the composer publishes an optimistic turn', async ({ page }) => {
  await page.goto('/#/agent');
  const feature = page.locator('main[data-route-id="agent"]');
  await expect(feature.locator('.agent-turn').first()).toBeVisible();

  const modelButton = page.getByRole('button', { name: /^模型：/ });
  await modelButton.click();
  const picker = page.getByRole('dialog');
  await expect(picker).toContainText('模型与推理强度');
  await picker.getByRole('button', { name: /推理/ }).click();
  const modelSelectionStartedAt = Date.now();
  await picker.getByRole('radio', { name: '高', exact: true }).click();
  await expect(picker).toBeHidden();
  expect(Date.now() - modelSelectionStartedAt).toBeLessThan(500);
  await expect(modelButton).toHaveAccessibleName(/思考强度：高/);

  const probe = `Session optimistic ${Date.now()}`;
  const composer = page.getByRole('textbox', { name: '消息' });
  await composer.fill(probe);
  const publishStartedAt = Date.now();
  await page.getByRole('button', { name: '发送', exact: true }).click();

  const optimisticTurn = feature.locator('.agent-turn', { hasText: probe });
  await expect(optimisticTurn).toBeVisible();
  expect(Date.now() - publishStartedAt).toBeLessThan(500);
  await expect(composer).toHaveValue('');
  await expect(optimisticTurn).toHaveCount(1);
});

test('Room publishes once immediately and preserves the in-flight turn across route switches', async ({ page }) => {
  await page.goto('/#/rooms');
  const feature = page.locator('main[data-route-id="rooms"]');
  await expect(feature).toBeVisible();

  const viewSelector = feature.getByRole('radiogroup', { name: '协作空间视图' });
  await expect(viewSelector.getByRole('radio', { name: '对话', exact: true })).toBeChecked();
  const timeline = feature.getByLabel('协作对话时间线');
  await expect(timeline).toBeVisible();
  const workspaceLayout = await feature.locator('.room-workspace').evaluate((root) => {
    const timelineElement = root.querySelector<HTMLElement>('[aria-label="协作对话时间线"]');
    const composerDock = root.querySelector<HTMLElement>('.room-composer-dock');
    if (!timelineElement || !composerDock) throw new Error('Room conversation layout is incomplete');
    const rootRect = root.getBoundingClientRect();
    const timelineRect = timelineElement.getBoundingClientRect();
    const composerRect = composerDock.getBoundingClientRect();
    return {
      clientWidth: root.clientWidth,
      scrollWidth: root.scrollWidth,
      root: { left: rootRect.left, right: rootRect.right, bottom: rootRect.bottom },
      timeline: { left: timelineRect.left, right: timelineRect.right },
      composer: { left: composerRect.left, right: composerRect.right, bottom: composerRect.bottom },
    };
  });
  expect(workspaceLayout.scrollWidth).toBeLessThanOrEqual(workspaceLayout.clientWidth + 1);
  expect(workspaceLayout.timeline.left).toBeGreaterThanOrEqual(workspaceLayout.root.left - 1);
  expect(workspaceLayout.timeline.right).toBeLessThanOrEqual(workspaceLayout.root.right + 1);
  expect(workspaceLayout.composer.left).toBeGreaterThanOrEqual(workspaceLayout.root.left - 1);
  expect(workspaceLayout.composer.right).toBeLessThanOrEqual(workspaceLayout.root.right + 1);
  expect(workspaceLayout.composer.bottom).toBeLessThanOrEqual(workspaceLayout.root.bottom + 1);

  const probe = `Room optimistic ${Date.now()}`;
  const composer = feature.getByRole('textbox', { name: '协作消息' });
  await composer.fill(probe);
  const publishStartedAt = Date.now();
  await feature.getByRole('button', { name: '立即干预当前回合' }).click();

  const optimisticTurn = feature.locator('article', { hasText: probe });
  await expect(optimisticTurn).toHaveCount(1);
  expect(Date.now() - publishStartedAt).toBeLessThan(500);
  await expect(optimisticTurn).toContainText('正在发送');
  await expect(composer).toHaveValue('');

  await page.evaluate(() => {
    window.location.hash = '#/agent';
  });
  await expect(page.locator('main[data-route-id="agent"]')).toBeVisible();
  await page.evaluate(() => {
    window.location.hash = '#/rooms';
  });
  await expect(page.locator('main[data-route-id="rooms"]')).toBeVisible();
  await expect(
    page.locator('main[data-route-id="rooms"] article', { hasText: probe }),
  ).toHaveCount(1);
});
