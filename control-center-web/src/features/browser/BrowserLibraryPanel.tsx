import {
  Bookmark,
  CheckCircle2,
  Download,
  ExternalLink,
  FileDown,
  FolderOpen,
  LoaderCircle,
  Trash2,
  X,
} from 'lucide-react';
import type { PawBrowserBookmark, PawBrowserDownload } from '@/paw-os/apps/paw-browser-host';
import { formatBytes } from '@/paw-os/apps/paw-browser-model';
import './browser-library.css';

export type BrowserLibraryView = 'bookmarks' | 'downloads';

type BrowserLibraryPanelProps = {
  view: BrowserLibraryView;
  bookmarks: PawBrowserBookmark[];
  downloads: PawBrowserDownload[];
  bookmarksAvailable: boolean;
  downloadsAvailable: boolean;
  currentPage?: { title: string; url: string };
  busy?: string;
  onAddBookmark?(): void;
  onClose(): void;
  onOpenBookmark(bookmark: PawBrowserBookmark): void;
  onRemoveBookmark(bookmarkId: string): void;
  onOpenDownload(downloadId: string): void;
  onRevealDownload(downloadId: string): void;
  onCancelDownload(downloadId: string): void;
  onOpenDownloadsFolder(): void;
};

const downloadStateLabels: Record<PawBrowserDownload['state'], string> = {
  pending: '等待下载',
  progressing: '下载中',
  completed: '已完成',
  cancelled: '已取消',
  interrupted: '已中断',
  failed: '失败',
};

export function BrowserLibraryPanel({
  view,
  bookmarks,
  downloads,
  bookmarksAvailable,
  downloadsAvailable,
  currentPage,
  busy = '',
  onAddBookmark,
  onClose,
  onOpenBookmark,
  onRemoveBookmark,
  onOpenDownload,
  onRevealDownload,
  onCancelDownload,
  onOpenDownloadsFolder,
}: BrowserLibraryPanelProps) {
  const isBookmarks = view === 'bookmarks';
  const currentPageCanBeBookmarked = Boolean(currentPage?.url && /^https?:\/\//i.test(currentPage.url));

  return (
    <section
      aria-label={isBookmarks ? '浏览书签' : '下载记录'}
      className="paw-browser-library"
      data-library-view={view}
    >
      <div className="paw-browser-surface-card paw-browser-library-card">
        <header>
          <div>
            {isBookmarks ? <Bookmark size={16} /> : <Download size={16} />}
            <strong>{isBookmarks ? '书签' : '下载记录'}</strong>
            <span className="paw-browser-library-count">{isBookmarks ? bookmarks.length : downloads.length}</span>
          </div>
          <div className="paw-browser-library-header-actions">
            {!isBookmarks ? (
              <button
                aria-label="打开下载目录"
                disabled={Boolean(busy)}
                onClick={onOpenDownloadsFolder}
                title="打开下载目录"
                type="button"
              >
                <FolderOpen size={14} />
              </button>
            ) : null}
            <button aria-label={`关闭${isBookmarks ? '书签' : '下载记录'}`} onClick={onClose} type="button">
              <X size={14} />
            </button>
          </div>
        </header>

        {isBookmarks ? (
          <div className="paw-browser-library-body">
            <div className="paw-browser-library-action-row">
              <button
                className="paw-browser-library-primary-action"
                disabled={!bookmarksAvailable || !currentPageCanBeBookmarked || Boolean(busy)}
                onClick={onAddBookmark}
                title={bookmarksAvailable ? (currentPageCanBeBookmarked ? '收藏当前页面' : '当前页面没有可收藏的网址') : '请更新 PAW 后使用书签'}
                type="button"
              >
                <Bookmark size={14} />
                收藏当前页面
              </button>
              {currentPageCanBeBookmarked ? <span title={currentPage?.url}>{currentPage?.title || currentPage?.url}</span> : null}
            </div>
            {!bookmarksAvailable ? (
              <LibraryUnavailable
                detail="请更新 PAW 后使用书签。"
              />
            ) : bookmarks.length ? (
              <ul className="paw-browser-library-list">
                {bookmarks.map((bookmark) => (
                  <li key={bookmark.id}>
                    <button className="paw-browser-library-item" onClick={() => onOpenBookmark(bookmark)} type="button">
                      <Bookmark size={14} />
                      <span>
                        <strong>{bookmark.title || bookmark.url}</strong>
                        <small>{bookmark.url}</small>
                      </span>
                      <ExternalLink aria-hidden="true" size={13} />
                    </button>
                    <button
                      aria-label={`删除书签 ${bookmark.title || bookmark.url}`}
                      className="paw-browser-library-remove"
                      disabled={Boolean(busy)}
                      onClick={() => onRemoveBookmark(bookmark.id)}
                      title="删除书签"
                      type="button"
                    >
                      <Trash2 size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="paw-browser-library-empty">还没有书签。打开一个页面后，收藏当前页面。</p>}
          </div>
        ) : (
          <div className="paw-browser-library-body">
            {!downloadsAvailable ? (
              <LibraryUnavailable
                detail="请更新 PAW 后使用下载记录。"
              />
            ) : downloads.length ? (
              <ul className="paw-browser-library-list paw-browser-download-list">
                {downloads.map((download) => (
                  <DownloadRow
                    busy={busy}
                    download={download}
                    key={download.id}
                    onCancel={onCancelDownload}
                    onOpen={onOpenDownload}
                    onReveal={onRevealDownload}
                  />
                ))}
              </ul>
            ) : <p className="paw-browser-library-empty">还没有下载记录。页面产生真实下载任务后，进度和结果会显示在这里。</p>}
          </div>
        )}
      </div>
    </section>
  );
}

function LibraryUnavailable({ detail }: { detail: string }) {
  return (
    <div className="paw-browser-library-unavailable" role="status">
      <LoaderCircle aria-hidden="true" size={17} />
      <strong>宿主能力不可用</strong>
      <p>{detail}</p>
    </div>
  );
}

function DownloadRow({
  busy,
  download,
  onCancel,
  onOpen,
  onReveal,
}: {
  busy: string;
  download: PawBrowserDownload;
  onCancel(downloadId: string): void;
  onOpen(downloadId: string): void;
  onReveal(downloadId: string): void;
}) {
  const active = download.state === 'pending' || download.state === 'progressing';
  const hasSavedFile = Boolean(download.path) && download.state === 'completed';
  const progress = download.totalBytes > 0
    ? Math.min(100, Math.round((download.receivedBytes / download.totalBytes) * 100))
    : null;
  const stateLabel = downloadStateLabels[download.state];

  return (
    <li className="paw-browser-download-row" data-state={download.state}>
      <div className="paw-browser-download-main">
        <span className="paw-browser-download-mark">
          {download.state === 'completed' ? <CheckCircle2 size={15} /> : <FileDown size={15} />}
        </span>
        <span className="paw-browser-download-copy">
          <strong title={download.filename}>{download.filename}</strong>
          <small title={download.url || download.path}>{download.url || download.path || '来源地址不可用'}</small>
          <span className="paw-browser-download-meta">
            <b>{stateLabel}</b>
            {progress !== null ? <span>{progress}% · {formatBytes(download.receivedBytes)} / {formatBytes(download.totalBytes)}</span> : download.receivedBytes ? <span>{formatBytes(download.receivedBytes)}</span> : null}
          </span>
          {progress !== null ? <progress aria-label={`下载进度 ${download.filename}`} max={100} value={progress} /> : null}
        </span>
      </div>
      <div className="paw-browser-download-actions">
        {hasSavedFile ? (
          <>
            <button aria-label={`打开下载 ${download.filename}`} disabled={Boolean(busy)} onClick={() => onOpen(download.id)} title="打开文件" type="button"><ExternalLink size={13} /></button>
            <button aria-label={`显示下载 ${download.filename}`} disabled={Boolean(busy)} onClick={() => onReveal(download.id)} title="显示所在文件夹" type="button"><FolderOpen size={13} /></button>
          </>
        ) : null}
        {active ? <button aria-label={`取消下载 ${download.filename}`} data-danger onClick={() => onCancel(download.id)} title="取消下载" type="button"><X size={13} /></button> : null}
      </div>
    </li>
  );
}
