import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const auditedRoutes = ['overview', 'agent', 'rooms', 'observability', 'configuration'] as const;

test('representative desktop and mobile routes have no WCAG A/AA violations', async ({
  page,
}, testInfo) => {
  test.skip(
    !['desktop-1440x900', 'mobile-390x844'].includes(testInfo.project.name),
    'one desktop and one mobile accessibility pass are sufficient',
  );

  for (const routeId of auditedRoutes) {
    await page.goto(`/#/${routeId}`);
    await expect(page.locator(`main[data-route-id="${routeId}"]`)).toBeVisible();
    await page.waitForTimeout(250);

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    await testInfo.attach(`axe-${routeId}.json`, {
      body: JSON.stringify(results.violations, null, 2),
      contentType: 'application/json',
    });

    expect(
      results.violations,
      `${routeId} has accessibility violations: ${results.violations
        .map((violation) => `${violation.id} (${violation.nodes.length})`)
        .join(', ')}`,
    ).toEqual([]);
  }
});
