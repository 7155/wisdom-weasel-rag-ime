/**
 * Read-only design probe. Opens every registered PAWOS App against the mock
 * transport and reports computed-style evidence for the design rules the
 * product owner grades against: one composition per first viewport, cards only
 * where they own interaction, bounded shadow depth, one type language, and
 * atmosphere rather than a flat fill.
 *
 * Not a test — it grades nothing and fails nothing. It writes one screenshot
 * per App plus a JSON report so a design review argues from what the product
 * renders rather than from what its stylesheets say.
 *
 * Start a dev server first, then:
 *   node scripts/design-audit-probe.mjs [baseUrl] [outDir]
 */
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';

const baseUrl = process.argv[2] || 'http://127.0.0.1:4176';
const outDir = process.argv[3] || 'test-results/design-audit';

// id + Launchpad label, mirroring `features/paw-os/model/app-registry.ts`.
// A plain .mjs cannot import the TypeScript registry; the App list changing
// without this list changing shows up as an open failure in the report.
const APPS = [
  ['agent', 'Agent'],
  ['project-workbench', '项目工作台'],
  ['files', 'Files'],
  ['terminal', 'Terminal'],
  ['memory', 'Memory'],
  ['knowledge', 'Knowledge'],
  ['browser', 'Browser'],
  ['input-studio', 'Input Studio'],
  ['app-center', 'App Center'],
  ['system-monitor', 'System Monitor'],
  ['system-settings', 'System Settings'],
];

const collect = () => {
  const px = (value) => Number.parseFloat(value) || 0;
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden'
      && Number(style.opacity) > 0 && rect.width > 2 && rect.height > 2;
  };
  const shell = document.querySelector('.paw-window-shell[data-active]')
    || [...document.querySelectorAll('.paw-window-shell')].at(-1);
  if (!shell) return { error: 'no window shell' };
  const body = shell.querySelector('.paw-window-body') || shell;
  const rect = body.getBoundingClientRect();
  const elements = [...body.querySelectorAll('*')].filter(visible);

  const shadowLayers = [];
  const pills = [];
  const fonts = new Map();
  const backdrops = [];
  let cards = 0;

  for (const element of elements) {
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();

    const shadow = style.boxShadow;
    if (shadow && shadow !== 'none') {
      const layers = shadow.split(/,(?![^()]*\))/).filter((part) => !part.includes('inset')).length;
      if (layers >= 3) shadowLayers.push({ selector: path(element), shadow, layers });
    }

    const radius = px(style.borderTopLeftRadius);
    if (radius >= 100 || (radius > 0 && radius >= box.height / 2 && box.width > box.height * 1.6)) {
      pills.push(path(element));
    }

    const family = style.fontFamily.split(',')[0].replace(/["']/g, '').trim();
    fonts.set(family, (fonts.get(family) || 0) + 1);

    if (style.backdropFilter && style.backdropFilter !== 'none') {
      backdrops.push({ selector: path(element), filter: style.backdropFilter });
    }

    // A card is a bounded, filled, elevated container that holds other
    // content. Rows in a list are not cards; a boxed promo is.
    const bordered = px(style.borderTopWidth) > 0 || (shadow && shadow !== 'none');
    const filled = style.backgroundColor !== 'rgba(0, 0, 0, 0)' && style.backgroundColor !== 'transparent';
    if (bordered && filled && radius >= 6 && box.width > 140 && box.height > 56
      && element.querySelectorAll('*').length > 2) cards += 1;
  }

  // First-viewport composition: how many top-level sibling blocks the reader
  // meets before scrolling.
  const firstScreen = [...body.querySelectorAll(':scope > *, :scope > * > *')]
    .filter(visible)
    .filter((element) => element.getBoundingClientRect().top < rect.top + 620)
    .filter((element) => element.getBoundingClientRect().height > 40);

  const scroller = body.querySelector('[data-testid="virtuoso-scroller"]') || body;
  const overflowX = body.scrollWidth - body.clientWidth;

  return {
    windowSize: [Math.round(rect.width), Math.round(rect.height)],
    elementCount: elements.length,
    cards,
    pillCount: pills.length,
    pillSamples: pills.slice(0, 6),
    multiLayerShadows: shadowLayers.slice(0, 8),
    multiLayerShadowCount: shadowLayers.length,
    backdropCount: backdrops.length,
    backdropSamples: backdrops.slice(0, 5),
    fontFamilies: [...fonts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6),
    firstScreenBlocks: firstScreen.length,
    bodyBackground: getComputedStyle(body).backgroundImage === 'none'
      ? getComputedStyle(body).backgroundColor
      : 'image',
    horizontalOverflow: overflowX,
    scrollerTag: scroller === body ? 'body' : 'virtuoso',
  };

  function path(element) {
    const parts = [];
    for (let node = element; node && parts.length < 3; node = node.parentElement) {
      const cls = [...node.classList].slice(0, 2).join('.');
      parts.unshift(cls ? `${node.tagName.toLowerCase()}.${cls}` : node.tagName.toLowerCase());
    }
    return parts.join(' > ');
  }
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
await mkdir(outDir, { recursive: true });

const report = {};
await page.goto(`${baseUrl}/?controlTransport=mock#/project-field`);
await page.locator('.paw-desktop-root').waitFor({ timeout: 30_000 });
await page.waitForTimeout(1_200);
await page.screenshot({ path: `${outDir}/00-desktop.png` });
report.desktop = await page.evaluate(() => ({
  dockButtons: document.querySelectorAll('.paw-dock button').length,
  desktopBackground: getComputedStyle(document.querySelector('.paw-desktop-root')).backgroundImage,
}));

for (const [id, label] of APPS) {
  try {
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: '全部 App', exact: true }).click({ timeout: 10_000 });
    const launcher = page.getByRole('dialog', { name: '全部 App' });
    await launcher.waitFor({ timeout: 8_000 });
    if (id === 'agent') await page.screenshot({ path: `${outDir}/00-launchpad.png` });
    await launcher.getByRole('button', { name: new RegExp(`^${label}`) }).first().click({ timeout: 10_000 });
    await launcher.waitFor({ state: 'hidden', timeout: 8_000 });
    const shell = page.locator(`.paw-window-shell[data-app="${id}"]`).last();
    await shell.waitFor({ timeout: 20_000 });
    for (let i = 0; i < 60; i += 1) {
      if (!(await shell.locator('.paw-app-boot, .paw-app-loading, .mgmt-loading, .ui-skeleton').count())) break;
      await page.waitForTimeout(300);
    }
    await page.waitForTimeout(500);
    report[id] = await shell.evaluate(collect);
    await page.screenshot({ path: `${outDir}/${id}.png` });
  } catch (error) {
    report[id] = { error: String(error).slice(0, 200) };
    await page.screenshot({ path: `${outDir}/${id}-error.png` });
  }
  const close = page.locator('.paw-window-shell[data-active] .paw-window-traffic-close').first();
  if (await close.count()) await close.click().catch(() => {});
  await page.waitForTimeout(200);
}

await writeFile(`${outDir}/report.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
