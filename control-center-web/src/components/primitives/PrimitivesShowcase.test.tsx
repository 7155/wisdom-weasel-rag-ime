import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { ToastProvider } from './Toast';
import { TooltipProvider } from './Tooltip';
import { PrimitivesShowcase } from './PrimitivesShowcase';

describe('PrimitivesShowcase', () => {
  it('keeps controls keyboard-operable and renders every primitive state', async () => {
    const user = userEvent.setup();
    render(
      <TooltipProvider delayDuration={0}>
        <ToastProvider>
          <PrimitivesShowcase />
        </ToastProvider>
      </TooltipProvider>,
    );

    expect(screen.getByRole('main', { name: 'Design system preview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '新建任务' })).toBeInTheDocument();

    const switchControl = screen.getByRole('switch', { name: '启用辅助候选' });
    expect(switchControl).toBeChecked();
    await user.click(switchControl);
    expect(switchControl).not.toBeChecked();

    await user.click(screen.getByRole('radio', { name: '舒展' }));
    expect(screen.getByRole('radio', { name: '舒展' })).toBeChecked();

    await user.click(screen.getByRole('button', { name: '连接详情' }));
    expect(screen.getByText('Sidecar 8766 · Mock transport')).toBeVisible();
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: '打开确认框' }));
    expect(screen.getByRole('dialog', { name: '应用设置变更' })).toBeVisible();
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: '更多操作' }));
    expect(screen.getByRole('menuitem', { name: '复制诊断摘要' })).toBeVisible();
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: '显示通知' }));
    expect(await screen.findByText('设置已保存')).toBeVisible();

    await user.click(screen.getByRole('tab', { name: '空态' }));
    expect(screen.getByText('没有匹配记录')).toBeVisible();
  });
});
