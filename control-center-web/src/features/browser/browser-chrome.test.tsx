import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => cleanup());
import { BrowserOmnibox } from './BrowserOmnibox';
import { BrowserPageStatus } from './BrowserPageStatus';
import { BrowserTabStrip, type BrowserTabItem } from './BrowserTabStrip';

const tabs: BrowserTabItem[] = [
  { id: 'a', title: '文档', active: true },
  { id: 'b', title: '加载中页面', active: false, loading: true },
  { id: 'c', title: '', active: false, favicon: 'https://example.com/icon.png' },
  { id: 'd', title: '坏页面', active: false, failed: true },
];

describe('BrowserTabStrip', () => {
  it('renders one real tab per guest with loading, favicon, and failure identity', () => {
    render(
      <BrowserTabStrip onClose={() => undefined} onNewTab={() => undefined} onSelect={() => undefined} tabs={tabs} />,
    );
    const strip = screen.getByRole('tablist', { name: 'PAW Browser 标签页' });
    const rendered = within(strip).getAllByRole('tab');
    expect(rendered).toHaveLength(4);
    expect(rendered[0]).toHaveAttribute('aria-selected', 'true');
    expect(rendered[1]).toHaveAttribute('aria-selected', 'false');
    expect(rendered[2]).toHaveTextContent('新标签页');
    expect(rendered[1].querySelector('.ui-spin')).not.toBeNull();
    expect(rendered[2].querySelector('img')).toHaveAttribute('src', 'https://example.com/icon.png');
    expect(strip.querySelector('.paw-browser-tab[data-failed]')).not.toBeNull();
    expect(within(strip).getAllByLabelText('关闭标签页')).toHaveLength(1);
  });

  it('reports selection, close, and new-tab intents with the exact tab id', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onNewTab = vi.fn();
    const onSelect = vi.fn();
    render(<BrowserTabStrip onClose={onClose} onNewTab={onNewTab} onSelect={onSelect} tabs={tabs} />);
    await user.click(screen.getByRole('tab', { name: /加载中页面/ }));
    expect(onSelect).toHaveBeenCalledWith('b');
    await user.click(screen.getByLabelText('关闭标签页'));
    expect(onClose).toHaveBeenCalledWith('a');
    await user.click(screen.getByRole('button', { name: '新建标签页' }));
    expect(onNewTab).toHaveBeenCalledTimes(1);
  });
});

describe('BrowserOmnibox', () => {
  it('shows a search icon while the draft differs from the committed page', () => {
    render(
      <BrowserOmnibox
        address="paw"
        currentUrl="https://example.com/"
        onAddressChange={() => undefined}
        onNavigate={() => undefined}
      />,
    );
    expect(document.querySelector(".paw-omnibox-icon[data-kind='search']")).not.toBeNull();
    expect(document.querySelector('.paw-lock-icon')).toBeNull();
  });

  it('locks only a committed HTTPS page and marks HTTP as unencrypted', () => {
    const { rerender } = render(
      <BrowserOmnibox
        address="https://example.com/"
        currentUrl="https://example.com/"
        onAddressChange={() => undefined}
        onNavigate={() => undefined}
      />,
    );
    expect(screen.getByTitle('连接已加密')).toHaveClass('paw-lock-icon');
    rerender(
      <BrowserOmnibox
        address="http://example.com/"
        currentUrl="http://example.com/"
        onAddressChange={() => undefined}
        onNavigate={() => undefined}
      />,
    );
    expect(screen.getByTitle('连接未加密')).toBeInTheDocument();
    expect(document.querySelector('.paw-lock-icon')).toBeNull();
  });

  it('submits the typed address and clears through the clear control', async () => {
    const user = userEvent.setup();
    const onAddressChange = vi.fn();
    const onNavigate = vi.fn();
    render(
      <BrowserOmnibox address="example.com" currentUrl="" onAddressChange={onAddressChange} onNavigate={onNavigate} />,
    );
    await user.type(screen.getByRole('textbox', { name: '页面地址' }), '{Enter}');
    expect(onNavigate).toHaveBeenCalledWith('example.com');
    await user.click(screen.getByRole('button', { name: '清除地址' }));
    expect(onAddressChange).toHaveBeenCalledWith('');
  });
});

describe('BrowserPageStatus', () => {
  it('renders nothing while the page is healthy', () => {
    const { container } = render(<BrowserPageStatus onRetry={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('explains a main-frame load failure and offers one real retry', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <BrowserPageStatus failure={{ code: -105, description: '', url: 'https://missing.example/' }} onRetry={onRetry} />,
    );
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('找不到这个网站');
    expect(alert).toHaveTextContent('https://missing.example/');
    await user.click(screen.getByRole('button', { name: '重新加载' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('reports a gone page process ahead of an older load failure', () => {
    render(
      <BrowserPageStatus
        crashedReason="crashed"
        failure={{ code: -105, description: '', url: 'https://missing.example/' }}
        onRetry={() => undefined}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('页面渲染进程崩溃');
    expect(screen.queryByText('https://missing.example/')).toBeNull();
  });
});
