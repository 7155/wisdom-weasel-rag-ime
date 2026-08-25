import { expect, test, type Page } from '@playwright/test';
import { pawOsAppRegistry, type PawOsAppId } from '../src/features/paw-os/model/app-registry';

type AppAuditEvidence = {
  appId: PawOsAppId;
  label: string;
  windowVisible: boolean;
  windowWidth: number;
  windowHeight: number;
  mainTextLength: number;
  interactiveCount: number;
  errorAlerts: string[];
  issues: string[];
};

const PAWOS_APPS = pawOsAppRegistry.map((app) => ({ id: app.id, label: app.label }));

test.describe('PAWOS App interface audit (ops)', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-1440x900', 'desktop PAWOS audit viewport');
  });

  test('each registered App opens with a usable window surface', async ({ page }, testInfo) => {
    test.setTimeout(180_000);
    await page.goto('/#/project-field');
    await expect(page.locator('.paw-desktop-root')).toBeVisible({ timeout: 30_000 });

    const evidence: AppAuditEvidence[] = [];

    for (const app of PAWOS_APPS) {
      await openAppFromLaunchpad(page, app.label);
      const shell = page.locator(`.paw-window-shell[data-app="${app.id}"]`).last();
      await expect(shell).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(280);

      const audit = await collectAppEvidence(page, app.id, app.label);
      evidence.push(audit);

      expect(audit.windowVisible, `${app.id} window did not render`).toBe(true);
      expect(audit.windowWidth, `${app.id} window too narrow`).toBeGreaterThan(320);
      expect(audit.windowHeight, `${app.id} window too short`).toBeGreaterThan(240);
      expect(audit.mainTextLength, `${app.id} rendered an empty surface`).toBeGreaterThan(6);
      expect(audit.interactiveCount, `${app.id} exposes no controls`).toBeGreaterThan(0);
      expect(audit.errorAlerts, `${app.id} shows error alerts`).toEqual([]);
      expect(audit.issues, `${app.id} audit issues`).toEqual([]);

      await testInfo.attach(`paw-os-${app.id}.png`, {
        body: await shell.screenshot({ animations: 'disabled' }),
        contentType: 'image/png',
      });

      await closeTopWindow(page);
    }

    await testInfo.attach('paw-os-apps-audit.json', {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    });
  });
});

async function openAppFromLaunchpad(page: Page, label: string): Promise<void> {
  await page.getByRole('button', { name: '全部 App' }).click();
  const launcher = page.getByRole('dialog', { name: '全部 App' });
  await expect(launcher).toBeVisible();
  await launcher.getByRole('button', { name: new RegExp(label) }).click();
  await expect(launcher).toBeHidden({ timeout: 5_000 });
}

async function closeTopWindow(page: Page): Promise<void> {
  const close = page.locator('.paw-window-shell[data-active] .paw-window-traffic-close').first();
  if (await close.count()) {
    await close.click();
    await page.waitForTimeout(120);
  }
}

async function collectAppEvidence(page: Page, appId: PawOsAppId, label: string): Promise<AppAuditEvidence> {
  return page.locator(`.paw-window-shell[data-app="${appId}"]`).last().evaluate((shell, values) => {
    const main = shell.querySelector('main') || shell;
    const isVisible = (element: Element) => {
      const style = getComputedStyle(element as HTMLElement);
      const rect = (element as HTMLElement).getBoundingClientRect();
      return style.display !== 'none'
        && style.visibility !== 'hidden'
        && Number(style.opacity) > 0
        && rect.width > 0
        && rect.height > 0;
    };
    const rect = shell.getBoundingClientRect();
    const interactives = [...main.querySelectorAll<HTMLElement>(
      'button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [role="tab"]',
    )].filter(isVisible);
    const errorAlerts = [...main.querySelectorAll<HTMLElement>('[role="alert"], .paw-browser-error')]
      .filter(isVisible)
      .map((element) => (element.innerText || element.textContent || '').trim().slice(0, 120))
      .filter(Boolean);
    const issues: string[] = [];
    if (rect.width < 320) issues.push(`window width ${Math.round(rect.width)}px`);
    if (rect.height < 240) issues.push(`window height ${Math.round(rect.height)}px`);
    const text = (main as HTMLElement).innerText?.trim() ?? '';
    if (text.length <= 6) issues.push('empty or nearly empty main surface');
    if (!interactives.length) issues.push('no visible interactive controls');
    if (errorAlerts.length) issues.push(`error alerts: ${errorAlerts.join('; ')}`);
    return {
      appId: values.appId,
      label: values.label,
      windowVisible: rect.width > 0 && rect.height > 0,
      windowWidth: rect.width,
      windowHeight: rect.height,
      mainTextLength: text.length,
      interactiveCount: interactives.length,
      errorAlerts,
      issues,
    };
  }, { appId, label });
}
