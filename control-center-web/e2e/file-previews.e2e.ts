import { expect, test, type Page } from '@playwright/test';
import { expectNoHorizontalPageOverflow } from './helpers';

const PNG_1X1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
);

test('managed Markdown, code, Diff, image, and static HTML previews stay usable and isolated', async ({ page }, testInfo) => {
  test.skip(
    !['desktop-1440x900', 'mobile-390x844'].includes(testInfo.project.name),
    'one desktop and one narrow viewport cover the preview shell',
  );
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('evil.example')) externalRequests.push(request.url());
  });
  await page.route('**/api/agent/media/*/content?*', async (route) => {
    await route.fulfill({
      body: PNG_1X1,
      contentType: 'image/png',
      headers: {
        'Cache-Control': 'private, no-store',
        'Content-Security-Policy': "default-src 'none'; sandbox",
        'X-Content-Type-Options': 'nosniff',
      },
    });
  });
  await page.goto('/e2e/fixtures/file-previews.html');

  await open(page, 'handoff.md');
  await expect(page.getByRole('heading', { name: '交接清单' })).toBeVisible();
  await close(page);

  await open(page, 'room-commit.ts');
  await expect(page.getByText(/roomCommit/).first()).toBeVisible();
  await close(page);

  await open(page, 'room-runtime.diff');
  await expect(page.locator('.agent-diff-file')).toContainText('runtime.ts');
  await expect(page.locator('.agent-diff-file')).toContainText('managedRoute');
  await page.getByRole('radio', { name: '并排' }).click();
  await expect(page.locator('.agent-diff-split').first()).toBeVisible();
  await close(page);

  await open(page, 'room-proof.png');
  await expect(page.getByRole('img', { name: 'room-proof.png' })).toBeVisible();
  await close(page);

  await open(page, 'acceptance-report.html');
  const iframe = page.locator('iframe[title="acceptance-report.html 静态预览"]');
  await expect(iframe).toHaveAttribute('sandbox', '');
  await expect(iframe.contentFrame().getByRole('heading', { name: '静态验收报告' })).toBeVisible();
  await expect(iframe.contentFrame().getByText('脚本与网络已隔离。')).toBeVisible();
  await expect(iframe.contentFrame().locator('script, form, iframe')).toHaveCount(0);
  await expectNoHorizontalPageOverflow(page);
  expect(externalRequests).toEqual([]);

  await testInfo.attach(`file-preview-${testInfo.project.name}.png`, {
    body: await page.screenshot({ animations: 'disabled', fullPage: false }),
    contentType: 'image/png',
  });
});

async function open(page: Page, fileName: string): Promise<void> {
  await page.getByRole('button', { name: `预览 ${fileName}` }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
}

async function close(page: Page): Promise<void> {
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: '关闭' }).click();
  await expect(dialog).toBeHidden();
}
