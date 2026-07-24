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
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThanOrEqual(7);
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

test('Room mobile drawer leaves the workspace full width and preserves narrow controls', async ({ page }, testInfo) => {
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto('/#/rooms');
    const feature = page.locator('main[data-route-id="rooms"]');
    const workspace = page.locator('.room-workspace');
    const rail = page.locator('.rooms-rail');
    const railTrigger = page.getByRole('button', { name: '打开 Rooms 列表' });
    const header = page.locator('.room-workspace > header');
    const tabs = page.getByRole('radiogroup', { name: 'Room 工作区' });
    const actions = page.locator('.room-header-actions');
    await expect(rail).toBeHidden();
    await expect(railTrigger).toBeVisible();
    await expect(header).toBeVisible();
    await expect(tabs).toBeVisible();
    await expect(actions).toBeVisible();
    await expect(page.getByRole('radio', { name: 'Sessions' })).toBeVisible();
    const [featureBox, workspaceBox, headerBox, tabsBox, actionsBox] = await Promise.all([
      feature.boundingBox(),
      workspace.boundingBox(),
      header.boundingBox(),
      tabs.boundingBox(),
      actions.boundingBox(),
    ]);
    expect(featureBox).not.toBeNull();
    expect(workspaceBox).not.toBeNull();
    expect(headerBox).not.toBeNull();
    expect(tabsBox).not.toBeNull();
    expect(actionsBox).not.toBeNull();
    expect(workspaceBox?.x).toBe(featureBox?.x);
    expect(workspaceBox?.width).toBeGreaterThanOrEqual((featureBox?.width ?? 0) - 1);
    expect((tabsBox?.y ?? 0) + (tabsBox?.height ?? 0)).toBeLessThanOrEqual((actionsBox?.y ?? 0) + 1);
    expect((tabsBox?.x ?? 0) + (tabsBox?.width ?? 0)).toBeLessThanOrEqual((headerBox?.x ?? 0) + (headerBox?.width ?? 0) + 1);
    expect((actionsBox?.x ?? 0) + (actionsBox?.width ?? 0)).toBeLessThanOrEqual((headerBox?.x ?? 0) + (headerBox?.width ?? 0) + 1);

    await railTrigger.click();
    await expect(rail).toBeVisible();
    await expect(rail).toHaveAttribute('role', 'dialog');
    await expect(rail).toHaveAttribute('aria-modal', 'true');
    await expect(page.getByRole('button', { name: '关闭 Rooms 列表' }).first()).toBeFocused();
    await expect(page.locator('.rooms-rail-backdrop')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(rail).toBeHidden();
    await expect(railTrigger).toBeFocused();

    await railTrigger.click();
    await page.locator('.rooms-rail-backdrop').click({ position: { x: width - 10, y: 120 } });
    await expect(rail).toBeHidden();
    await railTrigger.click();
    const roomChoice = rail.getByRole('button', { name: /^打开 Room：/ }).first();
    if (await roomChoice.count()) {
      await roomChoice.click();
      await expect(rail).toBeHidden();
    } else {
      await page.getByRole('button', { name: '关闭 Rooms 列表' }).first().click();
    }

    const activeTopic = page.locator('.room-topic-tabs > button[aria-current="true"]');
    if (await activeTopic.count()) {
      await expect(activeTopic).toBeVisible();
      const topicMeasurement = await activeTopic.evaluate((element) => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        text: element.textContent?.trim() ?? '',
      }));
      expect(topicMeasurement.text.length).toBeGreaterThan(0);
      expect(topicMeasurement.scrollWidth).toBeLessThanOrEqual(topicMeasurement.clientWidth + 1);
      if (width <= 360) await expect(page.locator('.room-work-summary')).toBeHidden();
    }

    const mentionChips = page.locator('.room-mention-chips');
    if (await mentionChips.count()) {
      const chips = mentionChips.getByRole('button');
      expect(await chips.count()).toBeGreaterThan(1);
      await mentionChips.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
      const [chipContainerBox, lastChipBox] = await Promise.all([
        mentionChips.boundingBox(),
        chips.last().boundingBox(),
      ]);
      expect(lastChipBox).not.toBeNull();
      expect((lastChipBox?.x ?? 0) + (lastChipBox?.width ?? 0)).toBeLessThanOrEqual((chipContainerBox?.x ?? 0) + (chipContainerBox?.width ?? 0) + 1);
    }
    if (width === 320) {
      await testInfo.attach('room-mobile-320-drawer-and-controls', {
        body: await page.screenshot({ animations: 'disabled', fullPage: false }),
        contentType: 'image/png',
      });
    }
    await expectNoHorizontalPageOverflow(page);
  }
});

test('Room drawer adopts mobile overlay semantics after a live resize', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/rooms');
  const rail = page.locator('.rooms-rail');
  await expect(rail).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(rail).toHaveAttribute('role', 'dialog');
  await expect(rail).toHaveAttribute('aria-modal', 'true');
  await page.getByRole('button', { name: '关闭 Rooms 列表' }).first().click();
  await expect(rail).toBeHidden();
  await expect(page.getByRole('button', { name: '打开 Rooms 列表' })).toBeFocused();
  await expectNoHorizontalPageOverflow(page);
});

test('capability lifecycle labels stay whole on narrow screens', async ({ page }) => {
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto('/#/plugins');
    const labels = page.locator('.capability-stage-legend b');
    await expect(labels).toHaveCount(6);
    const measurements = await labels.evaluateAll((items) => items.map((item) => {
      const label = item as HTMLElement;
      return {
        whiteSpace: getComputedStyle(label).whiteSpace,
        width: label.getBoundingClientRect().width,
        scrollWidth: label.scrollWidth,
      };
    }));
    for (const measurement of measurements) {
      expect(measurement.whiteSpace).toBe('nowrap');
      expect(measurement.scrollWidth).toBeLessThanOrEqual(measurement.width + 1);
    }
    await expectNoHorizontalPageOverflow(page);
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
