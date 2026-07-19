import { expect, test } from '@playwright/test';
import { expectNoHorizontalPageOverflow, isMobileViewport } from './helpers';

test('control center shell matches the viewport visual baseline', async ({ page }) => {
  await page.goto('/#/overview');
  await expect(page.locator('main[data-route-id="overview"]')).toBeVisible();
  await expectNoHorizontalPageOverflow(page);

  const mobile = isMobileViewport(page);
  if (mobile) {
    await expect(page.locator('.shell-sidebar')).toBeHidden();
    await expect(page.locator('.shell-mobile-nav')).toBeVisible();
  } else {
    await expect(page.locator('.shell-sidebar')).toBeVisible();
    await expect(page.locator('.shell-mobile-nav')).toBeHidden();
  }
  await expect(page).toHaveScreenshot('control-center-shell.png', { fullPage: false });
});

test('production-shaped fixture stays bounded and records a viewport screenshot', async ({
  page,
}, testInfo) => {
  await page.goto('/e2e/fixtures/load.html');
  await page.waitForFunction(() => Boolean(Reflect.get(window, '__RAG_IME_QA__')));
  await expectNoHorizontalPageOverflow(page);

  const screenshot = await page.screenshot({ animations: 'disabled', fullPage: false });
  await testInfo.attach(`load-fixture-${testInfo.project.name}`, {
    body: screenshot,
    contentType: 'image/png',
  });
});

test('plugin catalog keeps readable columns for long capability lists', async ({ page }) => {
  await page.goto('/#/plugins');
  const rows = page.locator('.plugins-list__item');
  await expect(rows).toHaveCount(7);
  await expectNoHorizontalPageOverflow(page);

  const measurements = await rows.evaluateAll((items) => items.map((item) => {
    const copy = item.querySelector<HTMLElement>('.plugins-list__copy');
    const meta = item.querySelector<HTMLElement>('.plugins-list__aside');
    return {
      copyWidth: copy?.getBoundingClientRect().width ?? 0,
      copyHeight: copy?.getBoundingClientRect().height ?? 0,
      metaScrollWidth: meta?.scrollWidth ?? 0,
      metaClientWidth: meta?.clientWidth ?? 0,
    };
  }));
  for (const measurement of measurements) {
    expect(measurement.copyWidth).toBeGreaterThan(140);
    expect(measurement.copyHeight).toBeLessThan(90);
    expect(measurement.metaScrollWidth).toBeLessThanOrEqual(measurement.metaClientWidth + 1);
  }
});

test('voice provider rows stay inside the management grid', async ({ page }) => {
  await page.goto('/#/voice');
  const feature = page.locator('main[data-route-id="voice"]');
  await expect(feature).toBeVisible();
  await expectNoHorizontalPageOverflow(page);

  const bounds = await feature.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    rows: [...element.querySelectorAll<HTMLElement>('.mgmt-list__row')].map((row) => ({
      clientWidth: row.clientWidth,
      scrollWidth: row.scrollWidth,
    })),
  }));
  expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.clientWidth + 1);
  expect(bounds.rows.length).toBeGreaterThan(0);
  for (const row of bounds.rows) {
    expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth + 1);
  }
});

test('closing the Agent session rail releases its grid column', async ({ page }) => {
  test.skip(isMobileViewport(page), 'mobile session rail is an overlay');
  const viewport = { width: 1_280, height: 640 };
  await page.setViewportSize(viewport);
  await page.goto('/#/agent');
  const feature = page.locator('main[data-route-id="agent"]');
  const conversation = page.locator('.agent-conversation');
  const composer = page.getByRole('textbox', { name: '消息' });
  const composerSurface = page.locator('.agent-composer');
  await expect(feature).toHaveAttribute('data-rail-open', 'true');
  await expect(page.locator('.agent-session-row').first()).toBeVisible();
  await expect(composer).toBeVisible();

  const [before, composerBefore, composerSurfaceBefore, featureBefore] = await Promise.all([
    conversation.boundingBox(),
    composer.boundingBox(),
    composerSurface.boundingBox(),
    feature.boundingBox(),
  ]);
  expect(composerBefore).not.toBeNull();
  expect(composerSurfaceBefore).not.toBeNull();
  expect(featureBefore).not.toBeNull();
  expect((composerSurfaceBefore?.y ?? 0) + (composerSurfaceBefore?.height ?? 0))
    .toBeLessThanOrEqual((featureBefore?.y ?? 0) + (featureBefore?.height ?? 0) + 1);
  expect((composerSurfaceBefore?.y ?? 0) + (composerSurfaceBefore?.height ?? 0))
    .toBeLessThanOrEqual(viewport.height + 1);

  await page.getByRole('button', { name: '收起任务列表' }).click();
  await expect(feature).toHaveAttribute('data-rail-open', 'false');
  await page.waitForTimeout(260);
  const [featureBox, after, composerAfter, composerSurfaceAfter] = await Promise.all([
    feature.boundingBox(),
    conversation.boundingBox(),
    composer.boundingBox(),
    composerSurface.boundingBox(),
  ]);

  expect(before).not.toBeNull();
  expect(featureBox).not.toBeNull();
  expect(after).not.toBeNull();
  expect(composerAfter).not.toBeNull();
  expect(composerSurfaceAfter).not.toBeNull();
  expect((before?.x ?? 0) - (after?.x ?? 0)).toBeGreaterThan(200);
  expect(Math.abs((after?.x ?? 0) - (featureBox?.x ?? 0))).toBeLessThanOrEqual(1);
  expect((after?.width ?? 0) - (before?.width ?? 0)).toBeGreaterThan(200);
  expect((composerSurfaceAfter?.y ?? 0) + (composerSurfaceAfter?.height ?? 0))
    .toBeLessThanOrEqual((featureBox?.y ?? 0) + (featureBox?.height ?? 0) + 1);
  expect((composerSurfaceAfter?.y ?? 0) + (composerSurfaceAfter?.height ?? 0))
    .toBeLessThanOrEqual(viewport.height + 1);
  await expectNoHorizontalPageOverflow(page);
});
