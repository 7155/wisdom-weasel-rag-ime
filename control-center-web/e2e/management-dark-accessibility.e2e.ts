import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { routes } from './helpers';

const auditedRoutes = routes.filter(({ id }) => !['agent', 'rooms'].includes(id));

test.use({ colorScheme: 'dark' });

test('management routes have no WCAG A/AA violations in dark mode', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  test.skip(
    !['desktop-1440x900', 'mobile-390x844'].includes(testInfo.project.name),
    'one desktop and one mobile dark-mode pass are sufficient',
  );

  for (const route of auditedRoutes) {
    await page.goto(`/?controlTransport=mock#/${route.id}`);
    await expect(page.locator(`main[data-route-id="${route.id}"]`)).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    // Let the route entrance finish before measuring contrast. Axe otherwise
    // samples partially composited text while the page is still fading in.
    await page.waitForTimeout(250);

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    expect(
      results.violations,
      `${route.id} has dark-mode accessibility violations: ${results.violations
        .map((violation) => `${violation.id} (${violation.nodes.length})`)
        .join(', ')}`,
    ).toEqual([]);
  }
});
