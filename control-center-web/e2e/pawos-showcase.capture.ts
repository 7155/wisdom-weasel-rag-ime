import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const webRoot = fileURLToPath(new URL('..', import.meta.url));
const outputRoot = path.join(webRoot, 'output', 'showcase');
const rawImageRoot = path.join(outputRoot, 'raw');

test('capture the public PAWOS Agent and Room showcase', async ({ page }) => {
  await mkdir(rawImageRoot, { recursive: true });
  await page.clock.setFixedTime(new Date('2026-08-27T04:00:00+08:00'));
  await page.addInitScript(() => window.localStorage.clear());
  const video = page.video();

  await page.goto(showcaseRoute('/agent?session=session-preview'));
  await expect(page.locator('.paw-session-workspace')).toBeVisible();
  await expect(page.locator('.paw-session-workspace__runtime')).toContainText('已同步');
  await pauseForReading(page);

  await page.getByRole('button', { name: 'Agent 轨迹' }).click();
  const trace = page.getByRole('region', { name: '当前 Agent 轨迹' });
  await expect(trace).toBeVisible();
  await trace.getByRole('tab', { name: '上下文装配' }).click();
  await expect(trace.getByRole('img', { name: '上下文 token 构成' })).toBeVisible();
  await pauseForReading(page);
  await capture(page, 'pawos-agent-trace.png');

  await page.evaluate(() => { window.location.hash = '/rooms?room=room-preview'; });
  const room = page.locator('.paw-room-workspace');
  await expect(room).toBeVisible();
  await expect(room).toContainText('任务图依赖验证');
  await expect(room).toHaveAttribute('data-status', 'synced');
  await pauseForReading(page);

  await page.getByRole('button', { name: '协作态势' }).click();
  await expect(page.getByRole('complementary', { name: 'Room 协作态势' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Sol 协作态势' })).toBeVisible();
  await pauseForReading(page);
  await page.getByRole('button', { name: '在卫星窗中打开协作态势' }).click();
  await expect(page.locator('[data-focus-layout="true"][data-collaboration-role="satellite"]')).toBeVisible();
  await pauseForReading(page);
  await capture(page, 'pawos-room-focus-satellite.png');

  const mainRoomWindow = page.locator('[data-paw-window-id="agent"]');
  await mainRoomWindow.locator('.paw-window-titlebar').click({ position: { x: 480, y: 18 } });
  await mainRoomWindow.getByRole('button', { name: '星空' }).click();
  const starfield = page.getByRole('region', { name: 'Room 星空' });
  await expect(starfield).toBeVisible();
  const switchTo2d = starfield.getByRole('button', { name: '切换为平面星空' });
  if (await switchTo2d.isVisible().catch(() => false)) await switchTo2d.click();
  await expect(starfield).toHaveAttribute('data-render', '2d');
  await page.evaluate(() => { document.documentElement.dataset.reduceMotion = 'true'; });
  await expect(starfield).toHaveAttribute('data-reduced-motion', 'true');
  await pauseForReading(page, 1_200);
  await capture(page, 'pawos-room-starfield.png');

  await page.close();
  if (video) await video.saveAs(path.join(outputRoot, 'pawos-showcase.webm'));
});

function showcaseRoute(route: string): string {
  return `/?frontend=paw-os&controlTransport=mock#${route}`;
}

async function pauseForReading(page: Page, durationMs = 850): Promise<void> {
  await page.mouse.move(1_400, 880);
  await page.waitForTimeout(durationMs);
}

async function capture(page: Page, name: string): Promise<void> {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.screenshot({
    animations: 'disabled',
    path: path.join(rawImageRoot, name),
    type: 'png',
  });
}
