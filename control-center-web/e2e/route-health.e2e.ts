import { expect, test, type Page } from '@playwright/test';
import { expectNoHorizontalPageOverflow, routes, settleAgentTimeline } from './helpers';

type RouteEvidence = {
  routeId: string;
  title: string;
  mainWidth: number;
  mainHeight: number;
  mainClientWidth: number;
  mainScrollWidth: number;
  textLength: number;
  interactiveCount: number;
  visibleInteractiveCount: number;
  blockedControls: string[];
  horizontalOverflowSources: string[];
  visibleTextOverflow: string[];
  documentClientWidth: number;
  documentScrollWidth: number;
};

test.describe('full route layout health', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(
      !['desktop-1440x900', 'mobile-390x844'].includes(testInfo.project.name),
      'the route matrix is intentionally fixed to the product desktop and narrow-screen viewports',
    );
  });

  test('all routes stay visible, bounded, and operable', async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    const evidence: RouteEvidence[] = [];

    for (const route of routes) {
      await page.goto(`/#/${route.id}`);
      const main = page.locator(`main[data-route-id="${route.id}"]`);
      await expect(main).toBeVisible();
      await expect(page.locator('.shell-topbar__title h1')).toHaveText(route.label);
      await expectNoHorizontalPageOverflow(page);
      await page.waitForTimeout(120);
      if (route.id === 'agent') {
        await expect(main.locator('.agent-turn').first()).toBeVisible();
        await settleAgentTimeline(page);
      }
      await expect.poll(
        async () => (await collectRouteEvidence(page, route.id, route.label)).interactiveCount,
        { message: `${route.id} did not expose a usable control after loading` },
      ).toBeGreaterThan(0);

      const routeEvidence = await collectRouteEvidence(page, route.id, route.label);
      evidence.push(routeEvidence);
      expect(routeEvidence.textLength, `${route.id} rendered an empty workspace`).toBeGreaterThan(8);
      expect(routeEvidence.mainWidth, `${route.id} did not fill the route stage`).toBeGreaterThan(300);
      expect(routeEvidence.mainHeight, `${route.id} collapsed vertically`).toBeGreaterThan(120);
      expect(
        routeEvidence.mainScrollWidth,
        `${route.id} main workspace is wider than its visible column`,
      ).toBeLessThanOrEqual(routeEvidence.mainClientWidth + 1);
      expect(
        routeEvidence.horizontalOverflowSources,
        `${route.id} has horizontal scrolling inside its main workspace`,
      ).toEqual([]);
      expect(routeEvidence.interactiveCount, `${route.id} exposes no usable controls`).toBeGreaterThan(0);
      expect(routeEvidence.blockedControls, `${route.id} has controls covered by another layer`).toEqual([]);
      expect(routeEvidence.visibleTextOverflow, `${route.id} has unclipped text escaping its box`).toEqual([]);

      await testInfo.attach(`${route.id}-${testInfo.project.name}.png`, {
        body: await page.screenshot({ animations: 'disabled', fullPage: false }),
        contentType: 'image/png',
      });
      await expectControlsActionable(page, route.id);
    }

    await testInfo.attach(`route-health-${testInfo.project.name}.json`, {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    });
  });

  test('desktop sidebar collapse releases the workspace column', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-1440x900', 'desktop shell contract');
    await page.goto('/#/overview');
    const shell = page.locator('.control-shell');
    const stage = page.locator('.shell-route-stage');
    const before = await stage.boundingBox();

    await page.getByRole('button', { name: '收起侧边栏' }).click();
    await expect(shell).toHaveAttribute('data-sidebar-collapsed', 'true');
    await page.waitForTimeout(260);
    const after = await stage.boundingBox();

    expect(before).not.toBeNull();
    expect(after).not.toBeNull();
    expect((before?.x ?? 0) - (after?.x ?? 0)).toBeGreaterThanOrEqual(147);
    expect((after?.width ?? 0) - (before?.width ?? 0)).toBeGreaterThanOrEqual(147);

    await page.locator('.shell-sidebar [data-route="memory"]').click();
    await expect(page.locator('main[data-route-id="memory"]')).toBeVisible();
    await expect(page.locator('.shell-topbar__title h1')).toHaveText('记忆');
    await expectNoHorizontalPageOverflow(page);

    await page.getByRole('button', { name: '展开侧边栏' }).click();
    await expect(shell).not.toHaveAttribute('data-sidebar-collapsed', 'true');
  });

  test('route changes reset document scroll before rendering the next workspace', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-1440x900', 'desktop document scrolling contract');
    await page.goto('/#/planning');
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);

    await page.locator('.shell-sidebar [data-route="overview"]').click();
    await expect(page.locator('main[data-route-id="overview"]')).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  });
});

async function collectRouteEvidence(page: Page, routeId: string, title: string): Promise<RouteEvidence> {
  return page.locator(`main[data-route-id="${routeId}"]`).evaluate((main, values) => {
    const isVisible = (element: HTMLElement) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none'
        && style.visibility !== 'hidden'
        && Number(style.opacity) > 0
        && rect.width > 0
        && rect.height > 0;
    };
    const describe = (element: HTMLElement) => {
      const label = element.getAttribute('aria-label')
        || element.getAttribute('title')
        || element.textContent
        || element.tagName.toLowerCase();
      return `${element.tagName.toLowerCase()}.${element.className || '<none>'}: ${label.trim().slice(0, 80)}`;
    };
    const centerInsideClippingAncestors = (element: HTMLElement) => {
      const bounds = element.getBoundingClientRect();
      const centerX = bounds.left + bounds.width / 2;
      const centerY = bounds.top + bounds.height / 2;
      let ancestor = element.parentElement;
      while (ancestor && ancestor !== main) {
        const style = getComputedStyle(ancestor);
        const ancestorBounds = ancestor.getBoundingClientRect();
        if (
          /(auto|scroll|hidden|clip)/u.test(style.overflowX)
          && (centerX < ancestorBounds.left || centerX >= ancestorBounds.right)
        ) return false;
        if (
          /(auto|scroll|hidden|clip)/u.test(style.overflowY)
          && (centerY < ancestorBounds.top || centerY >= ancestorBounds.bottom)
        ) return false;
        ancestor = ancestor.parentElement;
      }
      return true;
    };
    const interactives = [...main.querySelectorAll<HTMLElement>(
      'button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled)',
    )].filter(isVisible);
    const mobileNavigation = document.querySelector<HTMLElement>('.shell-mobile-nav');
    const visibleBottom = mobileNavigation && isVisible(mobileNavigation)
      ? mobileNavigation.getBoundingClientRect().top
      : window.innerHeight;
    const inViewport = interactives.filter((element) => {
      const rect = element.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      return centerX >= 0
        && centerX < window.innerWidth
        && centerY >= 0
        && centerY < visibleBottom
        && centerInsideClippingAncestors(element);
    });
    const blockedControls = inViewport.flatMap((element) => {
      const rect = element.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      // Composer toolbars intentionally occupy the padded footer of a textarea.
      // Probe its actual typing lane instead of the decorative/control footer.
      const y = element instanceof HTMLTextAreaElement
        ? rect.top + Math.min(18, rect.height / 4)
        : rect.top + rect.height / 2;
      const hit = document.elementFromPoint(x, y);
      return hit && (element === hit || element.contains(hit)) ? [] : [describe(element)];
    });
    const visibleTextOverflow = [...main.querySelectorAll<HTMLElement>(
      'h1, h2, h3, h4, p, span, strong, small, label, dt, dd, button, a',
    )]
      .filter(isVisible)
      .filter((element) => {
        const style = getComputedStyle(element);
        return element.scrollWidth > element.clientWidth + 2 && style.overflowX === 'visible';
      })
      .map(describe);
    const rect = main.getBoundingClientRect();
    const horizontalOverflowSources = [...main.querySelectorAll<HTMLElement>('*')]
      .filter(isVisible)
      .filter(centerInsideClippingAncestors)
      .filter((element) => {
        const bounds = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return style.position !== 'fixed'
          && bounds.right > rect.right + 1;
      })
      .slice(0, 12)
      .map((element) => {
        const bounds = element.getBoundingClientRect();
        const turn = element.closest<HTMLElement>('.agent-turn');
        const turnBounds = turn?.getBoundingClientRect();
        const assistantTurn = element.closest<HTMLElement>('.agent-assistant-turn');
        const assistantBounds = assistantTurn?.getBoundingClientRect();
        const assistantBody = element.closest<HTMLElement>('.agent-assistant-turn__body');
        const bodyBounds = assistantBody?.getBoundingClientRect();
        const blocks = element.closest<HTMLElement>('.agent-blocks');
        const blocksBounds = blocks?.getBoundingClientRect();
        const parentBounds = element.parentElement?.getBoundingClientRect();
        const turnEvidence = turn && turnBounds
          ? ` turn=${Math.round(turnBounds.left)}..${Math.round(turnBounds.right)}:${getComputedStyle(turn).boxSizing}`
          : '';
        const assistantEvidence = assistantBounds
          ? ` assistant=${Math.round(assistantBounds.left)}..${Math.round(assistantBounds.right)}`
          : '';
        const bodyEvidence = bodyBounds
          ? ` body=${Math.round(bodyBounds.left)}..${Math.round(bodyBounds.right)}`
          : '';
        const blocksEvidence = blocksBounds
          ? ` blocks=${Math.round(blocksBounds.left)}..${Math.round(blocksBounds.right)}`
          : '';
        const parentEvidence = parentBounds
          ? ` parent=${Math.round(parentBounds.left)}..${Math.round(parentBounds.right)}`
          : '';
        return `${describe(element)} [${Math.round(bounds.left)}..${Math.round(bounds.right)} / ${Math.round(rect.right)}${turnEvidence}${assistantEvidence}${bodyEvidence}${blocksEvidence}${parentEvidence}]`;
      });
    return {
      routeId: values.routeId,
      title: values.title,
      mainWidth: rect.width,
      mainHeight: rect.height,
      mainClientWidth: main.clientWidth,
      mainScrollWidth: main.scrollWidth,
      textLength: ((main as HTMLElement).innerText || '').trim().length,
      interactiveCount: interactives.length,
      visibleInteractiveCount: inViewport.length,
      blockedControls,
      horizontalOverflowSources,
      visibleTextOverflow,
      documentClientWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
    };
  }, { routeId, title });
}

async function expectControlsActionable(page: Page, routeId: string): Promise<void> {
  const controls = page.locator(
    `main[data-route-id="${routeId}"] button:not(:disabled), `
      + `main[data-route-id="${routeId}"] a[href], `
      + `main[data-route-id="${routeId}"] input:not(:disabled), `
      + `main[data-route-id="${routeId}"] textarea:not(:disabled), `
      + `main[data-route-id="${routeId}"] select:not(:disabled)`,
  );
  const count = await controls.count();
  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    if (!(await control.isVisible())) continue;
    const box = await control.boundingBox();
    const viewport = page.viewportSize();
    if (!box || !viewport) continue;
    const centerX = box.x + box.width / 2;
    const centerY = box.y + box.height / 2;
    if (centerX < 0 || centerX >= viewport.width || centerY < 0 || centerY >= viewport.height) continue;
    const receivesPointer = await control.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return Boolean(hit && (element === hit || element.contains(hit)));
    });
    if (!receivesPointer) continue;
    await control.click({ timeout: 2_000, trial: true });
  }
}
