import { expect, test } from '@playwright/test';

test('Room control plane stays readable and target Stop remains reachable', async ({ page }) => {
  await page.goto('/e2e/fixtures/room-kernel.html');

  const plane = page.getByRole('region', { name: 'Room 协作控制面' });
  await expect(plane).toBeVisible();
  await expect(page.getByRole('region', { name: /公开 Posts/ }).first()).toContainText('显式提交');
  await expect(page.getByRole('region', { name: /私有 Sessions/ }).first()).toContainText('过程不进入 Room');

  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(1);
  expect(overflow.body).toBeLessThanOrEqual(1);

  const stopButton = page.getByRole('button', { name: '停止' }).first();
  await stopButton.focus();
  await page.keyboard.press('Enter');
  const stop = await page.locator('body').getAttribute('data-last-stop');
  expect(JSON.parse(stop ?? '{}')).toMatchObject({
    schemaVersion: 'wisdom-weasel.room-kernel-command.v1',
    commandKind: 'cancel_root',
    roomId: 'room-kernel-qa',
    rootId: 'root-research-2026-07-19-with-a-deliberately-long-identifier',
    targetKind: 'root',
    targetId: 'root-research-2026-07-19-with-a-deliberately-long-identifier',
    generation: 3,
  });
  await expect(plane).toContainText('已接受 · root_cancelled');

  await page.screenshot({ path: test.info().outputPath('room-kernel-control.png'), fullPage: true });
});
