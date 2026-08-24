import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => cleanup());
import { BrowserOmnibox, committedUrlParts, omniboxCommitPreview } from './BrowserOmnibox';
import { BrowserPageStatus } from './BrowserPageStatus';
import { BrowserTabStrip, browserTabTooltip, type BrowserTabItem } from './BrowserTabStrip';

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
    expect(rendered[1]).toHaveAttribute('aria-busy', 'true');
    expect(rendered[2].querySelector('img')).toHaveAttribute('src', 'https://example.com/icon.png');
    expect(strip.querySelector('.paw-browser-tab[data-failed]')).not.toBeNull();
  });

  it('names each tab with its real load state and keeps one resting close affordance', () => {
    render(
      <BrowserTabStrip onClose={() => undefined} onNewTab={() => undefined} onSelect={() => undefined} tabs={tabs} />,
    );
    const strip = screen.getByRole('tablist', { name: 'PAW Browser 标签页' });
    const rendered = within(strip).getAllByRole('tab');
    expect(rendered[0]).toHaveAttribute('title', '文档');
    expect(rendered[1]).toHaveAttribute('title', '加载中页面（正在加载）');
    expect(rendered[3]).toHaveAttribute('title', '坏页面（加载失败）');
    // Only the selected tab exposes the plain close control; background tabs
    // carry their own named close revealed on hover.
    expect(within(strip).getAllByLabelText('关闭标签页')).toHaveLength(1);
    expect(within(strip).getByLabelText('关闭标签页：坏页面')).toBeInTheDocument();
    expect(within(strip).getByLabelText('关闭标签页：新标签页')).toBeInTheDocument();
    expect(browserTabTooltip({ id: 'x', title: '', active: false, loading: true })).toBe('新标签页（正在加载）');
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
    await user.click(screen.getByLabelText('关闭标签页：坏页面'));
    expect(onClose).toHaveBeenCalledWith('d');
    await user.click(screen.getByRole('button', { name: '新建标签页' }));
    expect(onNewTab).toHaveBeenCalledTimes(1);
  });

  it('closes any tab on middle click without changing the selection', () => {
    const onClose = vi.fn();
    const onSelect = vi.fn();
    render(<BrowserTabStrip onClose={onClose} onNewTab={() => undefined} onSelect={onSelect} tabs={tabs} />);
    fireEvent(
      screen.getByRole('tab', { name: /坏页面/ }),
      new MouseEvent('auxclick', { bubbles: true, button: 1 }),
    );
    expect(onClose).toHaveBeenCalledWith('d');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('follows the tablist keyboard pattern with a roving tab stop', () => {
    const onClose = vi.fn();
    const onSelect = vi.fn();
    render(<BrowserTabStrip onClose={onClose} onNewTab={() => undefined} onSelect={onSelect} tabs={tabs} />);
    const rendered = screen.getAllByRole('tab');
    expect(rendered[0]).toHaveAttribute('tabindex', '0');
    expect(rendered[1]).toHaveAttribute('tabindex', '-1');
    fireEvent.keyDown(rendered[0], { key: 'ArrowRight' });
    expect(onSelect).toHaveBeenCalledWith('b');
    fireEvent.keyDown(rendered[0], { key: 'End' });
    expect(onSelect).toHaveBeenCalledWith('d');
    fireEvent.keyDown(rendered[0], { key: 'ArrowLeft' });
    expect(onSelect).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(rendered[0], { key: 'Delete' });
    expect(onClose).toHaveBeenCalledWith('a');
  });

  it('falls back to the neutral globe when a reported favicon fails to load', () => {
    render(
      <BrowserTabStrip
        onClose={() => undefined}
        onNewTab={() => undefined}
        onSelect={() => undefined}
        tabs={[{ id: 'c', title: '图标页', active: true, favicon: 'https://example.com/broken.png' }]}
      />,
    );
    const icon = document.querySelector('.paw-browser-tab-icon img');
    expect(icon).not.toBeNull();
    fireEvent.error(icon as Element);
    expect(document.querySelector('.paw-browser-tab-icon img')).toBeNull();
    expect(document.querySelector('.paw-browser-tab-icon svg')).not.toBeNull();
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

  it('previews the exact URL Enter will open while editing', async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(
      <BrowserOmnibox
        address="example.com"
        currentUrl="https://old.example/"
        onAddressChange={() => undefined}
        onNavigate={onNavigate}
      />,
    );
    expect(screen.queryByRole('button', { name: '打开 https://example.com' })).toBeNull();
    await user.click(screen.getByRole('textbox', { name: '页面地址' }));
    const commit = screen.getByRole('button', { name: '打开 https://example.com' });
    await user.click(commit);
    expect(onNavigate).toHaveBeenCalledWith('example.com');
  });

  it('previews a web search for non-URL drafts and hides the preview at rest', async () => {
    const user = userEvent.setup();
    render(
      <BrowserOmnibox
        address="paw workbench"
        currentUrl=""
        onAddressChange={() => undefined}
        onNavigate={() => undefined}
      />,
    );
    await user.click(screen.getByRole('textbox', { name: '页面地址' }));
    const commit = screen.getByRole('button', { name: '搜索 paw workbench' });
    expect(commit).toHaveTextContent('Google');
    expect(omniboxCommitPreview('https://example.com/', 'https://example.com/')).toBeNull();
    expect(omniboxCommitPreview('', '')).toBeNull();
  });

  it('restores the committed address on Escape', () => {
    const onAddressChange = vi.fn();
    render(
      <BrowserOmnibox
        address="half-typed draft"
        currentUrl="https://example.com/"
        onAddressChange={onAddressChange}
        onNavigate={() => undefined}
      />,
    );
    fireEvent.keyDown(screen.getByRole('textbox', { name: '页面地址' }), { key: 'Escape' });
    expect(onAddressChange).toHaveBeenCalledWith('https://example.com/');
  });

  it('emphasizes the real host at rest without changing the field value', async () => {
    const user = userEvent.setup();
    render(
      <BrowserOmnibox
        address="https://example.com/path?q=1"
        currentUrl="https://example.com/path?q=1"
        onAddressChange={() => undefined}
        onNavigate={() => undefined}
      />,
    );
    const input = screen.getByRole('textbox', { name: '页面地址' });
    expect(input).toHaveValue('https://example.com/path?q=1');
    expect(document.querySelector('.paw-omnibox-field[data-presenting]')).not.toBeNull();
    expect(document.querySelector('.paw-omnibox-url-host')).toHaveTextContent('example.com');
    expect(document.querySelector('.paw-omnibox-url-rest')).toHaveTextContent('/path?q=1');
    await user.click(input);
    expect(document.querySelector('.paw-omnibox-presentation')).toBeNull();
    expect(input).toHaveValue('https://example.com/path?q=1');
  });

  it('only styles URL parts that reassemble to the exact committed string', () => {
    expect(committedUrlParts('https://example.com/path?q=1#top')).toEqual({
      scheme: 'https://',
      host: 'example.com',
      rest: '/path?q=1#top',
    });
    expect(committedUrlParts('about:blank')).toBeNull();
    expect(committedUrlParts('not a url')).toBeNull();
    expect(committedUrlParts('https://user:pass@example.com/')).toBeNull();
  });
});

describe('BrowserPageStatus', () => {
  afterEach(() => {
    delete (navigator as { clipboard?: unknown }).clipboard;
  });

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
    expect(alert).toHaveTextContent('错误代码 -105');
    expect(alert).toHaveTextContent('恢复在当前共享标签页内完成');
    await user.click(screen.getByRole('button', { name: '重新加载' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('shows the raw error code as evidence next to a named description', () => {
    render(
      <BrowserPageStatus
        failure={{ code: -106, description: 'ERR_INTERNET_DISCONNECTED', url: 'https://x.example/' }}
        onRetry={() => undefined}
      />,
    );
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('网络已断开');
    expect(alert).toHaveTextContent('ERR_INTERNET_DISCONNECTED');
    expect(alert).toHaveTextContent('错误代码 -106');
  });

  it('copies the exact failed address and reports the copy truthfully', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    render(
      <BrowserPageStatus failure={{ code: -7, description: '', url: 'https://slow.example/a' }} onRetry={() => undefined} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /复制网址/ }));
    expect(writeText).toHaveBeenCalledWith('https://slow.example/a');
    expect(await screen.findByRole('button', { name: /已复制/ })).toBeInTheDocument();
  });

  it('reports a copy failure instead of pretending success', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {} });
    render(
      <BrowserPageStatus failure={{ code: -7, description: '', url: 'https://slow.example/a' }} onRetry={() => undefined} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /复制网址/ }));
    expect(await screen.findByRole('button', { name: /复制失败/ })).toBeInTheDocument();
  });

  it('reports a gone page process ahead of an older load failure', () => {
    render(
      <BrowserPageStatus
        crashedReason="crashed"
        failure={{ code: -105, description: '', url: 'https://missing.example/' }}
        onRetry={() => undefined}
      />,
    );
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('页面渲染进程崩溃');
    expect(alert).toHaveTextContent('进程退出原因 crashed');
    expect(screen.queryByText('https://missing.example/')).toBeNull();
    expect(screen.queryByRole('button', { name: /复制网址/ })).toBeNull();
  });
});
