import { expect, test } from '@playwright/test';
import { expectNoHorizontalPageOverflow } from './helpers';

test.use({
  channel: process.env.PAW_E2E_SYSTEM_CHROME === '1' ? 'chrome' : undefined,
  video: 'off',
});

const viewports = [
  { width: 375, height: 812 },
  { width: 390, height: 844 },
  { width: 667, height: 375 },
  { width: 1_280, height: 820 },
] as const;

test('Project Field keeps its navigator reachable across compact viewports', async ({ page }) => {
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto('/#/project-field');

    const field = page.locator('main.project-field');
    const navigatorInput = page.locator('#project-navigator-input');
    await expect(field).toBeVisible();
    await expect(navigatorInput).toBeVisible();
    await expectNoHorizontalPageOverflow(page);

    const inputBox = await navigatorInput.boundingBox();
    expect(inputBox).not.toBeNull();
    expect(inputBox?.y).toBeGreaterThanOrEqual(0);
    expect((inputBox?.y ?? 0) + (inputBox?.height ?? 0)).toBeLessThanOrEqual(viewport.height + 1);
    if (viewport.width <= 820) expect(inputBox?.height).toBeGreaterThanOrEqual(44);
  }
});

test('Project Field paper cards preserve resized titles and requirements', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/#/project-field');
  await expect(page.locator('main.project-field')).toBeVisible();

  const paperCards = page.locator([
    '.project-field__viewport[data-mode="route"]',
    ':is(.room-island[data-layout="ordered-paper"], .room-island[data-layout="timeline-paper"])',
    '.room-requirement-card',
  ].join(' '));

  await paperCards.evaluateAll((cards) => {
    const selectors = [
      '.room-requirement-card__heading strong',
      '.room-requirement-card__requirement b',
    ];
    for (const card of cards) {
      for (const element of card.querySelectorAll<HTMLElement>(selectors.join(','))) {
        const fontSize = Number.parseFloat(getComputedStyle(element).fontSize);
        element.style.setProperty('font-size', `${fontSize * 2}px`, 'important');
      }
    }
  });

  const measurements = await paperCards.evaluateAll((cards) => cards.map((card) => {
    const content = card.querySelectorAll<HTMLElement>([
      '.room-requirement-card__heading strong',
      '.room-requirement-card__requirement b',
    ].join(','));
    return {
      cardClientHeight: card.clientHeight,
      cardOverflowY: getComputedStyle(card).overflowY,
      cardScrollHeight: card.scrollHeight,
      content: [...content].map((element) => ({
        clientHeight: element.clientHeight,
        overflowY: getComputedStyle(element).overflowY,
        scrollHeight: element.scrollHeight,
      })),
    };
  }));

  expect(measurements.length).toBeGreaterThan(0);
  expect(measurements.some((measurement) => (
    measurement.cardScrollHeight > measurement.cardClientHeight + 1
  ))).toBe(true);
  for (const measurement of measurements) {
    expect(measurement.cardOverflowY).toBe('auto');
    for (const item of measurement.content) {
      expect(item.overflowY).toBe('visible');
      expect(item.scrollHeight).toBeLessThanOrEqual(item.clientHeight + 1);
    }
  }
});
