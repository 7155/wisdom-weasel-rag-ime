import { expect, test, type Page } from '@playwright/test';
import { expectNoHorizontalPageOverflow } from './helpers';

const PNG_1X1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
);

test('managed Markdown, code, Diff, image, and interactive HTML previews stay usable', async ({ page }, testInfo) => {
  test.skip(
    !['desktop-1440x900', 'mobile-390x844'].includes(testInfo.project.name),
    'one desktop and one narrow viewport cover the preview shell',
  );
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('evil.example')) externalRequests.push(request.url());
  });
  await page.route('**/__paw_html_preview', async (route) => {
    await route.fulfill({
      body: ISOLATED_PREVIEW_BOOTSTRAP,
      contentType: 'text/html; charset=utf-8',
      headers: {
        'Content-Security-Policy': ISOLATED_PREVIEW_CSP,
        'Cache-Control': 'private, no-store',
      },
    });
  });
  await page.route('https://evil.example/**', async (route) => {
    const url = route.request().url();
    if (url.endsWith('.png')) {
      await route.fulfill({ body: PNG_1X1, contentType: 'image/png' });
      return;
    }
    if (url.endsWith('.css')) {
      await route.fulfill({ body: 'body{color:#173c32} form{margin-top:12px}', contentType: 'text/css' });
      return;
    }
    await route.fulfill({
      body: '脚本与远程资源已运行。',
      contentType: 'text/plain',
      headers: { 'Access-Control-Allow-Origin': '*' },
    });
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
  await close(page, 'handoff.md');

  await open(page, 'room-commit.ts');
  await expect(page.getByText(/roomCommit/).first()).toBeVisible();
  await close(page, 'room-commit.ts');

  await open(page, 'room-runtime.diff');
  await expect(page.locator('.agent-diff-file')).toContainText('runtime.ts');
  await expect(page.locator('.agent-diff-file')).toContainText('managedRoute');
  await page.getByRole('radio', { name: '并排' }).click();
  await expect(page.locator('.agent-diff-split').first()).toBeVisible();
  await close(page, 'room-runtime.diff');

  await open(page, 'room-proof.png');
  await expect(page.getByRole('img', { name: 'room-proof.png' })).toBeVisible();
  await close(page, 'room-proof.png');

  await open(page, 'acceptance-report.html');
  const iframe = page.locator('iframe[title="acceptance-report.html 交互预览"]');
  await expect(iframe).toHaveAttribute('sandbox', /allow-scripts/);
  await expect(iframe).toHaveAttribute('sandbox', /allow-forms/);
  await expect(iframe.contentFrame().getByRole('heading', { name: '交互验收报告' })).toBeVisible();
  await expect(iframe.contentFrame().getByText('脚本与远程资源已运行。')).toBeVisible();
  // The isolated preview contains the bootstrap loader and the authored
  // report script. Both are expected: the first decodes the source into the
  // sandbox, while the second provides the report's interaction.
  await expect(iframe.contentFrame().locator('script')).toHaveCount(2);
  await expect(iframe.contentFrame().locator('form')).toHaveCount(1);
  await expect(iframe.contentFrame().locator('link[rel="stylesheet"]')).toHaveCount(1);
  await iframe.contentFrame().getByRole('textbox', { name: '报告备注' }).fill('表单交互正常');
  await iframe.contentFrame().getByRole('button', { name: '更新报告' }).click();
  await expect(iframe.contentFrame().getByText('表单交互正常')).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: '关闭' }).click();
  await expect(page.getByRole('dialog')).toBeHidden();

  const inlineFrame = page.locator('iframe[title="HTML 输出预览"]');
  await expect(inlineFrame.contentFrame().getByRole('heading', { name: '页内 HTML 已渲染' })).toBeVisible();
  await inlineFrame.contentFrame().getByRole('textbox', { name: '页内报告备注' }).fill('页内交互正常');
  await inlineFrame.contentFrame().getByRole('button', { name: '更新页内报告' }).click();
  await expect(inlineFrame.contentFrame().getByRole('heading', { name: '页内交互正常' })).toBeVisible();
  await expectNoHorizontalPageOverflow(page);
  expect(externalRequests.some((url) => url.endsWith('/run'))).toBe(true);
  expect(externalRequests.some((url) => url.endsWith('/theme.css'))).toBe(true);
  expect(externalRequests.some((url) => url.endsWith('/image.png'))).toBe(true);

  await testInfo.attach(`file-preview-${testInfo.project.name}.png`, {
    body: await page.screenshot({ animations: 'disabled', fullPage: false }),
    contentType: 'image/png',
  });
});

const ISOLATED_PREVIEW_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline' https: http: blob: data:",
  "style-src 'unsafe-inline' https: http:",
  'img-src data: blob: https: http:',
  'connect-src https: http: ws: wss:',
  'form-action https: http:',
  'sandbox allow-forms allow-modals allow-pointer-lock allow-popups allow-scripts',
].join('; ');

const ISOLATED_PREVIEW_BOOTSTRAP = `<!doctype html><meta charset="utf-8"><script>
(() => {
  const encoded = location.hash.slice(1).replace(/-/g, '+').replace(/_/g, '/');
  const padded = encoded + '='.repeat((4 - encoded.length % 4) % 4);
  const binary = atob(padded);
  const source = new TextDecoder().decode(Uint8Array.from(binary, c => c.charCodeAt(0)));
  document.open(); document.write(source); document.close();
})();
</script>`;

/**
 * Generated HTML is delivered as a report card with its own labelled action
 * rather than the one-line chip every other managed file gets, so opening it
 * goes through that card and remains a sandboxed dialog. Ordinary managed files
 * expand beside their originating message so the user keeps conversation
 * context while inspecting them.
 */
async function open(page: Page, fileName: string): Promise<void> {
  if (/\.html?$/u.test(fileName)) {
    const card = page.locator('.agent-report-card', { hasText: fileName });
    await expect(card).toBeVisible();
    await card.getByRole('button', { name: '预览报告' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
  } else {
    await page.getByRole('button', { name: `展开 ${fileName}` }).click();
    await expect(page.getByRole('region', { name: `${fileName} 内联预览` })).toBeVisible();
  }
}

async function close(page: Page, fileName: string): Promise<void> {
  const inline = page.getByRole('region', { name: `${fileName} 内联预览` });
  await page.getByRole('button', { name: `收起 ${fileName}` }).click();
  await expect(inline).toBeHidden();
}
