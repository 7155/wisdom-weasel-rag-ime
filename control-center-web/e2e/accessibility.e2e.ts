import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { routes } from './helpers';

test('all desktop and mobile routes have no WCAG A/AA violations', async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  test.skip(
    !['desktop-1440x900', 'mobile-390x844'].includes(testInfo.project.name),
    'one desktop and one mobile accessibility pass are sufficient',
  );

  for (const route of routes) {
    await page.goto(`/#/${route.id}`);
    await expect(page.locator(`main[data-route-id="${route.id}"]`)).toBeVisible();
    await page.waitForTimeout(250);

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    await testInfo.attach(`axe-${route.id}.json`, {
      body: JSON.stringify(results.violations, null, 2),
      contentType: 'application/json',
    });

    expect(
      results.violations,
      `${route.id} has accessibility violations: ${results.violations
        .map((violation) => `${violation.id} (${violation.nodes.length})`)
        .join(', ')}`,
    ).toEqual([]);
  }
});
