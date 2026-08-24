import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { BrowserFeature } from '.';

describe('BrowserFeature', () => {
  it('is the direct PAW Browser rather than an extension setup surface', async () => {
    render(
      <ControlTransportProvider transport={createPreviewTransport()}>
        <BrowserFeature />
      </ControlTransportProvider>,
    );

    await waitFor(() => expect(screen.getByRole('textbox', { name: '页面地址' })).toBeInTheDocument());
    expect(screen.queryByText('Agent 拥有完整控制权')).not.toBeInTheDocument();
    expect(screen.queryByText(/隔离 Profile/)).not.toBeInTheDocument();
    expect(screen.queryByText(/配对码|加载浏览器助手|允许站点/)).not.toBeInTheDocument();
    expect(screen.queryByText('Ego 轨迹')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '显示 Agent 浏览器轨迹' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Agent 浏览器轨迹' })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Agent 浏览器任务' })).toBeInTheDocument();
    expect(screen.getByText('Agent 刚刚完成')).toBeInTheDocument();
    expect(screen.getByText('读取页面')).toBeInTheDocument();
  });
});
