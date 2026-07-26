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
    const railTrigger = page.getByRole('button', { name: '打开协作空间列表' });
    const header = page.locator('.room-workspace > header');
    const tabs = page.getByRole('radiogroup', { name: '协作空间视图' });
    const actions = page.locator('.room-header-actions');
    await expect(rail).toBeHidden();
    await expect(railTrigger).toBeVisible();
    await expect(header).toBeVisible();
    await expect(tabs).toBeVisible();
    await expect(actions).toBeVisible();
    await expect(page.getByRole('radio', { name: '伙伴' })).toBeVisible();
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
    expect(Math.abs(
      (tabsBox?.y ?? 0) + (tabsBox?.height ?? 0) / 2
      - ((actionsBox?.y ?? 0) + (actionsBox?.height ?? 0) / 2),
    )).toBeLessThanOrEqual(2);
    expect((tabsBox?.x ?? 0) + (tabsBox?.width ?? 0)).toBeLessThanOrEqual((actionsBox?.x ?? 0) + 1);
    expect((tabsBox?.x ?? 0) + (tabsBox?.width ?? 0)).toBeLessThanOrEqual((headerBox?.x ?? 0) + (headerBox?.width ?? 0) + 1);
    expect((actionsBox?.x ?? 0) + (actionsBox?.width ?? 0)).toBeLessThanOrEqual((headerBox?.x ?? 0) + (headerBox?.width ?? 0) + 1);

    await railTrigger.click();
    await expect(rail).toBeVisible();
    await expect(rail).toHaveAttribute('role', 'dialog');
    await expect(rail).toHaveAttribute('aria-modal', 'true');
    await expect(page.getByRole('button', { name: '关闭协作空间列表' }).first()).toBeFocused();
    await expect(page.locator('.rooms-rail-backdrop')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(rail).toBeHidden();
    await expect(railTrigger).toBeFocused();

    await railTrigger.click();
    await page.locator('.rooms-rail-backdrop').click({ position: { x: width - 10, y: 120 } });
    await expect(rail).toBeHidden();
    await railTrigger.click();
    const roomChoice = rail.getByRole('button', { name: /^打开协作空间：/ }).first();
    if (await roomChoice.count()) {
      await roomChoice.click();
      await expect(rail).toBeHidden();
    } else {
      await page.getByRole('button', { name: '关闭协作空间列表' }).first().click();
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

test('Room releases desktop side panels after a live resize', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/rooms');
  const feature = page.locator('main[data-route-id="rooms"]');
  const rail = page.locator('.rooms-rail');
  await expect(rail).toBeVisible();
  await page.getByRole('button', { name: '看看协作进展' }).click();
  await expect(feature).toHaveAttribute('data-status-open', 'true');

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(rail).toBeHidden();
  await expect(feature).toHaveAttribute('data-status-open', 'false');
  await expect(page.getByRole('button', { name: '打开协作空间列表' })).toBeVisible();
  await expectNoHorizontalPageOverflow(page);
});

test('Session releases desktop side panels after a live resize', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/agent');
  const feature = page.locator('main[data-route-id="agent"]');
  const rail = page.locator('.agent-session-rail');
  await expect(feature).toHaveAttribute('data-rail-open', 'true');
  await expect(rail).toBeVisible();
  await page.getByRole('button', { name: '展开状态面板' }).click();
  await expect(feature).toHaveAttribute('data-status-open', 'true');

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(feature).toHaveAttribute('data-rail-open', 'false');
  await expect(feature).toHaveAttribute('data-status-open', 'false');
  await expect(rail).toHaveAttribute('aria-hidden', 'true');
  await expect(rail).toHaveAttribute('inert', '');
  await expect(page.locator('.agent-conversation')).toBeVisible();
  await expect(page.getByRole('button', { name: '展开对话列表' })).toBeVisible();
  await expect.poll(async () => {
    const [featureBox, railBox, conversationBox] = await Promise.all([
      feature.boundingBox(),
      rail.boundingBox(),
      page.locator('.agent-conversation').boundingBox(),
    ]);
    return {
      railReleased: (railBox?.x ?? 0) + (railBox?.width ?? 0) <= (featureBox?.x ?? 0) + 1,
      conversationAligned: Math.abs((conversationBox?.x ?? 0) - (featureBox?.x ?? 0)) <= 1,
      conversationFullWidth: (conversationBox?.width ?? 0) >= (featureBox?.width ?? 0) - 1,
    };
  }).toEqual({
    railReleased: true,
    conversationAligned: true,
    conversationFullWidth: true,
  });
  await expectNoHorizontalPageOverflow(page);
});

test('Session and Room share narrow-desktop status drawer behavior', async ({ page }) => {
  await page.setViewportSize({ width: 1_280, height: 820 });
  await page.goto('/#/agent');
  const agentConversation = page.locator('.agent-conversation');
  const agentStatusTrigger = page.getByRole('button', { name: '展开状态面板' });
  await expect(page.getByRole('separator', { name: '调整对话列表宽度' })).toBeVisible();
  await expect(page.getByRole('separator', { name: '调整状态面板宽度' })).toBeHidden();
  await agentStatusTrigger.click();
  const agentStatus = page.getByRole('dialog', { name: '当前对话状态' });
  await expect(agentStatus).toHaveAttribute('aria-modal', 'true');
  await expect(agentConversation).toHaveAttribute('inert', '');
  await page.keyboard.press('Escape');
  await expect(page.locator('.agent-status-panel')).toHaveAttribute('aria-hidden', 'true');
  await expect(agentStatusTrigger).toBeFocused();

  await page.goto('/#/rooms');
  const roomWorkspace = page.locator('.room-workspace');
  const roomStatusTrigger = page.getByRole('button', { name: '看看协作进展' });
  await expect(page.getByRole('separator', { name: '调整协作空间列表宽度' })).toBeVisible();
  await expect(page.getByRole('separator', { name: '调整协作进展面板宽度' })).toBeHidden();
  await roomStatusTrigger.click();
  const roomStatus = page.getByRole('dialog', { name: '协作进展' });
  await expect(roomStatus).toHaveAttribute('aria-modal', 'true');
  await expect(roomWorkspace).toHaveAttribute('inert', '');
  await page.keyboard.press('Escape');
  await expect(page.locator('.room-status-panel')).toHaveAttribute('aria-hidden', 'true');
  await expect(roomStatusTrigger).toBeFocused();
  await expectNoHorizontalPageOverflow(page);
});

test('Room tablet header keeps tabs, Room actions, and global actions in separate lanes', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 768 });
  await page.goto('/#/rooms');

  const workspace = page.locator('.room-workspace');
  const header = page.locator('.room-workspace > header');
  const title = header.locator(':scope > span');
  const tabs = page.getByRole('radiogroup', { name: '协作空间视图' });
  const roomActions = page.locator('.room-header-actions');
  const globalActions = page.locator('.shell-topbar__actions');

  await expect(workspace).toBeVisible();
  await expect(title).toBeHidden();
  await expect(tabs).toBeVisible();
  await expect(roomActions).toBeVisible();
  await expect(globalActions).toBeVisible();

  const [workspaceBounds, headerBounds, tabsBounds, roomActionBounds, globalActionBounds] = await Promise.all([
    workspace.evaluate((element) => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth })),
    header.boundingBox(),
    tabs.boundingBox(),
    roomActions.boundingBox(),
    globalActions.boundingBox(),
  ]);

  expect(workspaceBounds.scrollWidth).toBeLessThanOrEqual(workspaceBounds.clientWidth + 1);
  expect(headerBounds?.height).toBeCloseTo(48, 3);
  expect((tabsBounds?.x ?? 0) + (tabsBounds?.width ?? 0)).toBeLessThanOrEqual((roomActionBounds?.x ?? 0) + 1);
  expect((roomActionBounds?.x ?? 0) + (roomActionBounds?.width ?? 0)).toBeLessThanOrEqual((globalActionBounds?.x ?? 0) + 1);
  await expectNoHorizontalPageOverflow(page);
});

test('Session and Room headers float over full-height timelines without hiding the first item', async ({ page }) => {
  await page.setViewportSize({ width: 1_440, height: 900 });
  await page.goto('/#/agent');

  const conversation = page.locator('.agent-conversation');
  const sessionHeader = page.locator('.agent-conversation__header');
  const agentTimeline = page.locator('.agent-timeline');
  const agentScroller = agentTimeline.locator('[data-virtuoso-scroller="true"]');
  const agentSpacer = page.locator('.agent-timeline__header-space');
  const firstAgentTurn = agentTimeline.locator('article').first();
  const sessionComposer = page.locator('.agent-composer');
  await expect(firstAgentTurn).toBeVisible();
  await agentScroller.evaluate((element) => { element.scrollTop = 0; });

  const [conversationBox, sessionHeaderBox, agentTimelineBox, agentSpacerBox, firstAgentTurnBox, sessionComposerBox, sessionHeaderStyle, sessionComposerStyle] = await Promise.all([
    conversation.boundingBox(),
    sessionHeader.boundingBox(),
    agentTimeline.boundingBox(),
    agentSpacer.boundingBox(),
    firstAgentTurn.boundingBox(),
    sessionComposer.boundingBox(),
    sessionHeader.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        position: style.position,
        backgroundColor: style.backgroundColor,
        backdropFilter: style.backdropFilter,
      };
    }),
    sessionComposer.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        backgroundColor: style.backgroundColor,
        backdropFilter: style.backdropFilter,
      };
    }),
  ]);
  expect(sessionHeaderStyle.position).toBe('absolute');
  expect(sessionHeaderStyle.backgroundColor).toContain('rgba');
  expect(sessionHeaderStyle.backdropFilter).toContain('blur');
  expect(Math.abs((agentTimelineBox?.y ?? 0) - (conversationBox?.y ?? 0))).toBeLessThanOrEqual(1);
  expect(agentSpacerBox?.height).toBeGreaterThanOrEqual(sessionHeaderBox?.height ?? 0);
  expect(firstAgentTurnBox?.y).toBeGreaterThanOrEqual((sessionHeaderBox?.y ?? 0) + (sessionHeaderBox?.height ?? 0) - 1);

  await page.goto('/#/rooms');
  const roomHeader = page.locator('.room-workspace > header');
  const roomContext = page.locator('.room-context-bar');
  const roomTimeline = page.locator('.room-timeline');
  const roomScroller = roomTimeline.locator('[data-virtuoso-scroller="true"]');
  const roomSpacer = page.locator('.room-timeline__header-space');
  const firstRoomTurn = page.locator('.room-turn').first();
  const roomComposer = page.locator('.room-composer');
  await expect(firstRoomTurn).toBeVisible();
  await roomScroller.evaluate((element) => { element.scrollTop = 0; });

  const [roomHeaderBox, roomContextBox, roomTimelineBox, roomSpacerBox, firstRoomTurnBox, roomComposerBox, roomHeaderStyle, roomComposerStyle] = await Promise.all([
    roomHeader.boundingBox(),
    roomContext.boundingBox(),
    roomTimeline.boundingBox(),
    roomSpacer.boundingBox(),
    firstRoomTurn.boundingBox(),
    roomComposer.boundingBox(),
    roomHeader.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        position: style.position,
        backgroundColor: style.backgroundColor,
        backdropFilter: style.backdropFilter,
      };
    }),
    roomComposer.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        backgroundColor: style.backgroundColor,
        backdropFilter: style.backdropFilter,
      };
    }),
  ]);
  expect(roomHeaderStyle.position).toBe('absolute');
  expect(roomHeaderStyle.backgroundColor).toBe(sessionHeaderStyle.backgroundColor);
  expect(roomHeaderStyle.backdropFilter).toBe(sessionHeaderStyle.backdropFilter);
  expect(roomComposerStyle).toEqual(sessionComposerStyle);
  expect(Math.abs((roomComposerBox?.height ?? 0) - (sessionComposerBox?.height ?? 0))).toBeLessThanOrEqual(1);
  expect(Math.abs((roomTimelineBox?.y ?? 0) - (roomHeaderBox?.y ?? 0))).toBeLessThanOrEqual(1);
  expect(roomSpacerBox?.height).toBeGreaterThanOrEqual((roomContextBox?.y ?? 0) + (roomContextBox?.height ?? 0) - (roomHeaderBox?.y ?? 0));
  expect(firstRoomTurnBox?.y).toBeGreaterThanOrEqual((roomContextBox?.y ?? 0) + (roomContextBox?.height ?? 0) - 1);
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

  await page.getByRole('button', { name: '收起对话列表' }).click();
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
