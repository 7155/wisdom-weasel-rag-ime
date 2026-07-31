import { expect, test } from '@playwright/test';

test('Room control plane stays readable and target Stop remains reachable', async ({ page }) => {
  await page.goto('/e2e/fixtures/room-kernel.html');

  const plane = page.getByRole('region', { name: '协作任务进展' });
  await expect(plane).toBeVisible();
  await expect(page.getByRole('region', { name: '公开结果与回复' }).first()).toContainText('显式提交');
  await expect(page.getByRole('region', { name: '伙伴运行状态' }).first()).toContainText('不公开私有思考或对话正文');
  const planeAlignment = await plane.evaluate((root) => {
    const postHeader = root.querySelector('.room-kernel-posts > header')?.getBoundingClientRect();
    const sessionHeader = root.querySelector('.room-kernel-sessions > header')?.getBoundingClientRect();
    const postRow = root.querySelector('.room-kernel-posts > article')?.getBoundingClientRect();
    const sessionRow = root.querySelector('.room-kernel-sessions > details')?.getBoundingClientRect();
    if (!postHeader || !sessionHeader || !postRow || !sessionRow) return null;
    return {
      sideBySide: Math.abs(postHeader.left - sessionHeader.left) > 1,
      headerTopDelta: Math.abs(postHeader.top - sessionHeader.top),
      headerBottomDelta: Math.abs(postHeader.bottom - sessionHeader.bottom),
      firstRowTopDelta: Math.abs(postRow.top - sessionRow.top),
      headerLeftDelta: Math.abs(postHeader.left - sessionHeader.left),
      sessionHeaderTop: sessionHeader.top,
      postRowBottom: postRow.bottom,
    };
  });
  expect(planeAlignment).not.toBeNull();
  if (planeAlignment!.sideBySide) {
    expect(planeAlignment!.headerTopDelta).toBeLessThanOrEqual(1);
    expect(planeAlignment!.headerBottomDelta).toBeLessThanOrEqual(1);
    expect(planeAlignment!.firstRowTopDelta).toBeLessThanOrEqual(1);
  } else {
    expect(planeAlignment!.headerLeftDelta).toBeLessThanOrEqual(1);
    expect(planeAlignment!.sessionHeaderTop).toBeGreaterThanOrEqual(planeAlignment!.postRowBottom);
  }

  await page.getByText('查看验收与证据详情', { exact: true }).click();
  const requirements = page.getByRole('region', { name: /需求、证明与审查/ });
  await expect(requirements).toContainText('永久保留，不可修改');
  await expect(requirements).toContainText('验收标准');
  await expect(requirements).toContainText('伙伴的文字说明不能代替验证');
  await expect(requirements.locator('[data-gate-status="warn_blocked"] [data-status="observed_pass"]')).toHaveCount(0);
  await expect(requirements.getByText('任务收工检查')).toBeVisible();
  await expect(requirements.getByText('始终启用')).toBeVisible();
  await expect(requirements.getByRole('textbox')).toHaveCount(0);
  const original = requirements.getByLabel('第 1 条原始需求只读文本');
  await original.focus();
  await expect(original).toBeFocused();

  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  expect(overflow.document).toBeLessThanOrEqual(1);
  expect(overflow.body).toBeLessThanOrEqual(1);

  const stopButton = page.getByRole('button', { name: '停止此任务' }).first();
  await stopButton.focus();
  await page.keyboard.press('Enter');
  const stop = await page.locator('body').getAttribute('data-last-stop');
  expect(JSON.parse(stop ?? '{}')).toMatchObject({
    schemaVersion: 'wisdom-weasel.room-kernel-command.v1',
    commandKind: 'cancel_root',
    roomId: 'room-kernel-qa',
    rootId: 'root-implementation',
    targetKind: 'root',
    targetId: 'root-implementation',
    generation: 1,
  });
  await expect(plane).toContainText('停止请求已接受');

  await page.screenshot({ path: test.info().outputPath('room-kernel-control.png'), fullPage: true });
});
