import { expect, test, type Page } from '@playwright/test';
import { expectNoHorizontalPageOverflow } from './helpers';

type FixtureMetrics = {
  history: {
    total: number;
    rendered: number;
    visibleAtMs: number;
    renderCostMs: number;
  };
  stream: {
    events: number;
    commits: number;
    complete: boolean;
    durationMs: number;
    p95PaintMs: number;
    longTasksOver50Ms: number;
  };
  typing: {
    samples: number;
    p95PaintMs: number;
  };
};

test.beforeEach(async ({ page }) => {
  await page.goto('/e2e/fixtures/load.html');
  await page.waitForFunction(() => Boolean(Reflect.get(window, '__RAG_IME_QA__')));
});

test('1,000-message history keeps a bounded DOM and readable long content', async ({ page }) => {
  const metrics = await readMetrics(page);
  expect(metrics.history.total).toBe(1_000);
  expect(metrics.history.rendered).toBe(48);
  expect(metrics.history.visibleAtMs).toBeLessThan(800);
  expect(metrics.history.renderCostMs).toBeLessThan(100);
  await expect(page.locator('[data-testid="history-window"] [data-turn]')).toHaveCount(48);
  await expect(page.locator('[data-testid="long-markdown"]')).toContainText('长 Markdown');
  await expect(page.locator('[data-media-kind]')).toHaveCount(2);
  await expectNoHorizontalPageOverflow(page);
});

test('200 delta/s is batched while the composer remains responsive', async ({ page }, testInfo) => {
  await page.getByTestId('start-stream').click();
  await page.getByTestId('composer').pressSequentially(
    'streaming keeps this composer responsive while events are committed',
    { delay: 8 },
  );
  await page.waitForFunction(
    () => Boolean((Reflect.get(window, '__RAG_IME_QA__') as { metrics: FixtureMetrics }).metrics.stream.complete),
    undefined,
    { timeout: 5_000 },
  );

  const metrics = await readMetrics(page);
  await testInfo.attach('streaming-performance.json', {
    body: JSON.stringify(metrics, null, 2),
    contentType: 'application/json',
  });
  expect(metrics.stream.events).toBe(200);
  expect(metrics.stream.commits).toBeLessThan(100);
  expect(metrics.stream.commits).toBeGreaterThan(10);
  expect(metrics.stream.p95PaintMs).toBeLessThan(50);
  expect(metrics.stream.durationMs).toBeLessThan(1_800);
  expect(metrics.stream.longTasksOver50Ms).toBe(0);
  expect(metrics.typing.samples).toBeGreaterThan(20);
  expect(metrics.typing.p95PaintMs).toBeLessThan(50);
  await expect(page.getByTestId('stream-output')).toContainText('Δ200');
});

test('tool, approval, Room, subagent, and reconnect states remain operable', async ({ page }) => {
  await expect(page.locator('[data-tool-call]')).toHaveCount(8);
  await expect(page.locator('[data-approval]')).toHaveCount(4);
  await expect(page.getByTestId('room-participants').locator('li')).toHaveCount(3);
  await expect(page.getByTestId('subagent-list').locator('li')).toHaveCount(4);

  const tool = page.locator('[data-tool-call="tool-1"]');
  await tool.locator('summary').click();
  await expect(tool).toHaveAttribute('open', '');

  const approval = page.locator('[data-approval="approval-1"]');
  await approval.getByRole('button', { name: '批准' }).click();
  await expect(approval).toContainText('receipt-1');

  await page.getByTestId('toggle-connection').click();
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'offline');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'reconnecting');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'online');
});

async function readMetrics(page: Page): Promise<FixtureMetrics> {
  return page.evaluate(() => {
    const fixture = Reflect.get(window, '__RAG_IME_QA__') as { metrics?: FixtureMetrics } | undefined;
    if (!fixture?.metrics) throw new Error('QA fixture metrics are unavailable');
    return fixture.metrics;
  });
}
