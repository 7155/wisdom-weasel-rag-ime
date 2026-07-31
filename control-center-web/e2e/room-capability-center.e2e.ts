import { expect, test } from '@playwright/test';

test('Room capability and binding inspectors remain separated and responsive', async ({ page }) => {
  await page.goto('/e2e/fixtures/room-capability-center.html');

  await expect(page.getByRole('region', { name: 'Root Task Dispatch 拓扑' })).toContainText('Root / Task / Dispatch');
  await expect(page.getByRole('region', { name: 'root-research Tasks' })).toContainText('task-verify-room-routing');
  await expect(page.getByRole('region', { name: 'root-research Dispatches' })).toContainText('dispatch-research-attempt-2');
  const researchRoot = page.locator('.room-kernel-root').first();
  await expect(researchRoot.getByRole('region', { name: '公开结果与回复' })).toContainText('显式提交');
  await expect(researchRoot.getByRole('region', { name: '伙伴运行状态' })).toContainText('不公开私有思考或对话正文');

  const capability = page.getByRole('button', { name: /知识检索/ });
  await capability.focus();
  await page.keyboard.press('Enter');
  await expect(capability).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('region', { name: '知识检索 收窄记录' })).toContainText('角色书');
  await expect(page.getByRole('region', { name: 'Participant Binding 检查器' })).toContainText('room-binding-a');
  await expect(page.getByRole('button', { name: '停止' })).toHaveCount(2);

  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(1);
  expect(overflow.body).toBeLessThanOrEqual(1);

  const buttonsFit = await page.getByRole('button', { name: /知识检索|长期记忆写入/ }).evaluateAll((buttons) => buttons.every((button) => {
    const parent = button.parentElement?.getBoundingClientRect();
    const box = button.getBoundingClientRect();
    return Boolean(parent && box.left >= parent.left - 1 && box.right <= parent.right + 1);
  }));
  expect(buttonsFit).toBe(true);

  const stateLabelsDoNotOverlap = await page.locator('.capability-center__state-header span').evaluateAll((labels) => labels.every((label, index) => {
    if (index === 0) return true;
    const previous = labels[index - 1]!.getBoundingClientRect();
    const current = label.getBoundingClientRect();
    return previous.right <= current.left + 1;
  }));
  expect(stateLabelsDoNotOverlap).toBe(true);

  expect(await page.getByRole('button', { name: /activate|rollback|revoke|启用|回滚|撤销/i }).count()).toBe(0);
  await page.screenshot({ path: test.info().outputPath('room-capability-center.png'), fullPage: true });
});
