import { expect, test } from '@playwright/test';

test('CollaborationProfile control stays keyboard-readable without mobile overflow', async ({ page }) => {
  await page.goto('/e2e/fixtures/collaboration-profile.html');
  const control = page.getByRole('region', { name: '高级：角色书管理' });
  await control.locator(':scope > details > summary').click();
  await expect(control).toContainText('角色书当前设置已同步');
  await expect(control).toContainText('当前版本');
  await expect(control.getByText('仅用于新开始的对话')).toBeVisible();
  const prompt = control.getByLabel('角色书说明（高级只读）');
  await prompt.focus();
  await expect(prompt).toBeFocused();
  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(1);
  expect(overflow.body).toBeLessThanOrEqual(1);
  await expect(control.getByRole('button', { name: '启用', exact: true })).toBeDisabled();
});
