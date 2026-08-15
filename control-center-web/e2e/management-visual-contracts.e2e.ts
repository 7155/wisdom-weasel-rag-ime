import { expect, test } from '@playwright/test';

test('desktop empty-state guidance is visible when the surrounding pane first appears', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-1440x900', 'desktop split-pane contract');

  await page.goto('/?controlTransport=mock#/plugins');

  const detailPane = page.getByLabel('能力详情占位');
  const guidance = detailPane.getByText('选择一项能力查看详情');
  await expect(detailPane).toBeVisible();
  await expect(guidance).toBeVisible();

  const paneBox = await detailPane.boundingBox();
  const guidanceBox = await guidance.boundingBox();
  expect(paneBox).not.toBeNull();
  expect(guidanceBox).not.toBeNull();
  expect(guidanceBox!.y).toBeGreaterThanOrEqual(paneBox!.y);
  expect(guidanceBox!.y + guidanceBox!.height).toBeLessThanOrEqual(900);
});
