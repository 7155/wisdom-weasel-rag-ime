import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PawBrowserBookmark, PawBrowserDownload } from '@/paw-os/apps/paw-browser-host';
import { BrowserLibraryPanel } from './BrowserLibraryPanel';

afterEach(cleanup);

const bookmark: PawBrowserBookmark = {
  id: 'bookmark-docs',
  title: 'PAW docs',
  url: 'https://example.com/docs',
  createdAt: 10,
  updatedAt: 10,
};

const download: PawBrowserDownload = {
  id: 'download-report',
  filename: 'report.pdf',
  url: 'https://example.com/report.pdf',
  path: '/Users/example/Downloads/report.pdf',
  state: 'progressing',
  receivedBytes: 50,
  totalBytes: 100,
  startedAt: 10,
  updatedAt: 20,
};

function renderPanel(overrides: Partial<Parameters<typeof BrowserLibraryPanel>[0]> = {}) {
  return render(
    <BrowserLibraryPanel
      bookmarks={[]}
      bookmarksAvailable
      currentPage={{ title: 'Current page', url: 'https://example.com/current' }}
      downloads={[]}
      downloadsAvailable
      onAddBookmark={vi.fn()}
      onCancelDownload={vi.fn()}
      onClose={vi.fn()}
      onOpenBookmark={vi.fn()}
      onOpenDownload={vi.fn()}
      onOpenDownloadsFolder={vi.fn()}
      onRemoveBookmark={vi.fn()}
      onRevealDownload={vi.fn()}
      view="bookmarks"
      {...overrides}
    />,
  );
}

describe('BrowserLibraryPanel', () => {
  it('persists the current page through the host callback and opens or removes stored bookmarks', async () => {
    const user = userEvent.setup();
    const onAddBookmark = vi.fn();
    const onOpenBookmark = vi.fn();
    const onRemoveBookmark = vi.fn();
    renderPanel({ bookmarks: [bookmark], onAddBookmark, onOpenBookmark, onRemoveBookmark });

    await user.click(screen.getByRole('button', { name: '收藏当前页面' }));
    expect(onAddBookmark).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: /^PAW docs/ }));
    expect(onOpenBookmark).toHaveBeenCalledWith(bookmark);
    await user.click(screen.getByRole('button', { name: '删除书签 PAW docs' }));
    expect(onRemoveBookmark).toHaveBeenCalledWith('bookmark-docs');
  });

  it('shows real download progress and routes open, reveal, and cancel to host jobs', async () => {
    const user = userEvent.setup();
    const onOpenDownload = vi.fn();
    const onRevealDownload = vi.fn();
    const onCancelDownload = vi.fn();
    const onOpenDownloadsFolder = vi.fn();
    const first = renderPanel({
      view: 'downloads',
      downloads: [{ ...download, state: 'completed' }],
      onOpenDownload,
      onRevealDownload,
      onCancelDownload,
      onOpenDownloadsFolder,
    });

    const region = screen.getByRole('region', { name: '下载记录' });
    expect(within(region).getByText('已完成')).toBeInTheDocument();
    await user.click(within(region).getByRole('button', { name: '打开下载 report.pdf' }));
    await user.click(within(region).getByRole('button', { name: '显示下载 report.pdf' }));
    await user.click(within(region).getByRole('button', { name: '打开下载目录' }));
    expect(onOpenDownload).toHaveBeenCalledWith('download-report');
    expect(onRevealDownload).toHaveBeenCalledWith('download-report');
    expect(onOpenDownloadsFolder).toHaveBeenCalledTimes(1);

    first.unmount();
    const active = renderPanel({ view: 'downloads', downloads: [download], onCancelDownload });
    expect(active.container.querySelector('progress')).toHaveAttribute('value', '50');
    await user.click(screen.getByRole('button', { name: '取消下载 report.pdf' }));
    expect(onCancelDownload).toHaveBeenCalledWith('download-report');
  });

  it('explains when the old host cannot provide library persistence instead of showing fake local records', () => {
    renderPanel({ view: 'downloads', downloadsAvailable: false, downloads: [download] });
    expect(screen.getByRole('status')).toHaveTextContent('请更新 PAW 后使用下载记录');
    expect(screen.queryByText('report.pdf')).toBeNull();
  });
});
