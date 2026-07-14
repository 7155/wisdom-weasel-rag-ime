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
  const rows = page.locator('.mgmt-list__row');
  await expect(rows).toHaveCount(6);
  await expectNoHorizontalPageOverflow(page);

  const measurements = await rows.evaluateAll((items) => items.map((item) => {
    const copy = item.querySelector<HTMLElement>('.mgmt-list__copy');
    const meta = item.querySelector<HTMLElement>('.mgmt-list__meta');
    return {
      copyWidth: copy?.getBoundingClientRect().width ?? 0,
      copyHeight: copy?.getBoundingClientRect().height ?? 0,
      metaScrollWidth: meta?.scrollWidth ?? 0,
      metaClientWidth: meta?.clientWidth ?? 0,
    };
  }));
  for (const measurement of measurements) {
    expect(measurement.copyWidth).toBeGreaterThan(180);
    expect(measurement.copyHeight).toBeLessThan(100);
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
  await page.goto('/#/agent');
  const feature = page.locator('main[data-route-id="agent"]');
  const conversation = page.locator('.agent-conversation');
  await expect(feature).toHaveAttribute('data-rail-open', 'true');
  await expect(page.locator('.agent-session-row').first()).toBeVisible();

  const before = await conversation.boundingBox();
  await page.getByRole('button', { name: '收起 Sessions' }).click();
  await expect(feature).toHaveAttribute('data-rail-open', 'false');
  await page.waitForTimeout(260);
  const [featureBox, after] = await Promise.all([
    feature.boundingBox(),
    conversation.boundingBox(),
  ]);

  expect(before).not.toBeNull();
  expect(featureBox).not.toBeNull();
  expect(after).not.toBeNull();
  expect((before?.x ?? 0) - (after?.x ?? 0)).toBeGreaterThan(200);
  expect(Math.abs((after?.x ?? 0) - (featureBox?.x ?? 0))).toBeLessThanOrEqual(1);
  expect((after?.width ?? 0) - (before?.width ?? 0)).toBeGreaterThan(200);
  await expectNoHorizontalPageOverflow(page);
});
