import { expect, test } from '@playwright/test';

test('CollaborationProfile control stays keyboard-readable without mobile overflow', async ({ page }) => {
  await page.goto('/e2e/fixtures/collaboration-profile.html');
  const control = page.getByRole('region', { name: '角色书正式控制面' });
  await expect(control).toContainText('canonical projection 已同步');
  await expect(control).toContainText('Pointer revision');
  await expect(control.getByText('仅新 Root 使用')).toBeVisible();
  const prompt = control.getByLabel('角色书提示词只读文本');
  await prompt.focus();
  await expect(prompt).toBeFocused();
  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(1);
  expect(overflow.body).toBeLessThanOrEqual(1);
  await expect(control.getByRole('button', { name: '启用' })).toBeDisabled();
});
