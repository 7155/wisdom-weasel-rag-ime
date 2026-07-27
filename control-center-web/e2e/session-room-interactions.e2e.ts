import { expect, test } from '@playwright/test';

test('model changes close immediately and the composer publishes an optimistic turn', async ({ page }) => {
  await page.goto('/#/agent');
  const feature = page.locator('main[data-route-id="agent"]');
  await expect(feature.locator('.agent-turn').first()).toBeVisible();

  const modelButton = page.getByRole('button', { name: /^模型：/ });
  await modelButton.click();
  const picker = page.getByRole('dialog');
  await expect(picker).toContainText('模型与推理强度');
  const modelSelectionStartedAt = Date.now();
  await picker.getByRole('button', { name: '高', exact: true }).click();
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

  const executionLayout = await feature.locator('.room-execution-phase').evaluate((root) => {
    const boxes = Array.from(root.children).map((element) => {
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
    });
    const overlaps = boxes.flatMap((first, firstIndex) => boxes.slice(firstIndex + 1).map((second) => ({
      width: Math.max(0, Math.min(first.right, second.right) - Math.max(first.left, second.left)),
      height: Math.max(0, Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top)),
    })));
    return {
      overlaps,
      rootWidth: root.getBoundingClientRect().width,
      scrollWidth: root.scrollWidth,
    };
  });
  expect(executionLayout.scrollWidth - executionLayout.rootWidth).toBeLessThanOrEqual(1);
  for (const overlap of executionLayout.overlaps) {
    expect(overlap.width * overlap.height).toBeLessThanOrEqual(0.5);
  }

  const probe = `Room optimistic ${Date.now()}`;
  const composer = feature.getByRole('textbox', { name: '协作消息' });
  await composer.fill(probe);
  const publishStartedAt = Date.now();
  await feature.getByRole('button', { name: '发送消息' }).click();

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
