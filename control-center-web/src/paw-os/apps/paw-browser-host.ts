import type { RefObject } from 'react';

export const PAW_BROWSER_PARTITION = 'persist:paw-browser';

export type PawBrowserHost = {
  kind: 'electron-webview';
  partition: string;
  activate(tab: { title: string; url: string; webContentsId: number }): void;
  clearBrowsingData(action: 'cache' | 'site-data'): Promise<PawBrowserMaintenanceReceipt>;
  clearHistory(): Promise<PawBrowserHistoryEntry[]>;
  getHistory(): Promise<PawBrowserHistoryEntry[]>;
  getSettings(): Promise<PawBrowserSettings>;
  openDownloads(): Promise<{ opened: boolean; path: string }>;
  pickWorkspaceDirectory?(): Promise<PawWorkspaceDirectoryReceipt | null>;
  register(tab: { commandId?: string; tabId: string; webContentsId: number }): void;
  removeHistoryEntry(entryId: string): Promise<PawBrowserHistoryEntry[]>;
  setStartPage(startPage: string): Promise<{ startPage: string }>;
  takeScreenshot(webContentsId: number): Promise<{ path: string; saved: boolean }>;
  onCommand(listener: (command: { action: 'new_tab'; commandId: string; url: string }) => void): () => void;
  onGuestClosed(listener: (tabId: string) => void): () => void;
  onHistoryChanged(listener: (history: PawBrowserHistoryEntry[]) => void): () => void;
  onOpenUrl(listener: (url: string) => void): () => void;
  onSelectTab(listener: (tabId: string) => void): () => void;
};

export type PawWorkspaceDirectoryReceipt = {
  name: string;
  path: string;
};

export type PawBrowserHistoryEntry = {
  id: string;
  title: string;
  url: string;
  visitedAt: number;
};

export type PawBrowserSettings = {
  cacheBytes: number;
  cookieCount: number;
  downloadPath: string;
  partition: typeof PAW_BROWSER_PARTITION;
  permissionMode: 'site-request';
  startPage: string;
};

export type PawBrowserMaintenanceReceipt = {
  action: 'cache' | 'site-data';
  after: number;
  before: number;
  completedAt: number;
};

export type PawBrowserWebview = HTMLElement & {
  canGoBack(): boolean;
  canGoForward(): boolean;
  getTitle(): string;
  getURL(): string;
  getWebContentsId(): number;
  getZoomFactor(): number;
  goBack(): void;
  goForward(): void;
  findInPage(text: string, options?: { findNext?: boolean; forward?: boolean }): number;
  loadURL(url: string): Promise<void>;
  print(): void;
  reload(): void;
  setZoomFactor(value: number): void;
  stop(): void;
  stopFindInPage(action: 'clearSelection' | 'keepSelection' | 'activateSelection'): void;
};

export function pawBrowserHost(): PawBrowserHost | null {
  const host = window.pawBrowserHost;
  return host?.kind === 'electron-webview' && host.partition === PAW_BROWSER_PARTITION
    ? host
    : null;
}

export function loadPawBrowserUrl(
  ref: RefObject<PawBrowserWebview | null>,
  rawUrl: string,
): boolean {
  const webview = ref.current;
  if (!webview) return false;
  void webview.loadURL(rawUrl);
  return true;
}
