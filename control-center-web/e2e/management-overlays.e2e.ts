import { expect, test } from '@playwright/test';

test.describe('management overlays', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile-390x844', 'mobile portal and touch contract');
  });

  test('keeps portal controls touchable and returns focus after a controlled dialog', async ({ page }) => {
    await page.goto('/?controlTransport=mock#/overview');
    await page.getByRole('button', { name: '外观与动效' }).click();

    const menuItems = page.getByRole('menuitemradio');
    await expect(menuItems).toHaveCount(6);
    for (const item of await menuItems.all()) {
      const box = await item.boundingBox();
      expect(Math.round(box?.height ?? 0)).toBeGreaterThanOrEqual(44);
    }
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: '外观与动效' })).toBeFocused();

    await page.goto('/?controlTransport=mock#/history');
    const recordSelect = page.getByRole('combobox', { name: '选择记录' });
    await recordSelect.click();
    for (const option of await page.getByRole('option').all()) {
      const box = await option.boundingBox();
      expect(Math.round(box?.height ?? 0)).toBeGreaterThanOrEqual(44);
    }
    await page.keyboard.press('Escape');
    await expect(recordSelect).toBeFocused();

    await page.goto('/?controlTransport=mock#/planning');
    const opener = page.getByRole('button', { name: '查看今日安排' });
    await opener.click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.keyboard.press('Escape');

    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(opener).toBeFocused();
  });
});
