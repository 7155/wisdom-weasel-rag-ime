const { contextBridge, ipcRenderer } = require('electron');

const nativeHost = process.platform === 'darwin' ? 'macos' : 'electron';
if (nativeHost === 'macos') {
  const markNativeHost = () => { document.documentElement.dataset.pawNativeHost = nativeHost; };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', markNativeHost, { once: true });
  else markNativeHost();
}

contextBridge.exposeInMainWorld('pawBrowserHost', Object.freeze({
  kind: 'electron-webview',
  nativeHost,
  partition: 'persist:paw-browser',
  activate(tab) {
    ipcRenderer.send('paw-browser:activate', tab);
  },
  clearBrowsingData(action) {
    return ipcRenderer.invoke('paw-browser:clear-browsing-data', action);
  },
  clearHistory() {
    return ipcRenderer.invoke('paw-browser:clear-history');
  },
  getHistory() {
    return ipcRenderer.invoke('paw-browser:get-history');
  },
  getSettings() {
    return ipcRenderer.invoke('paw-browser:get-settings');
  },
  listExtensions() {
    return ipcRenderer.invoke('paw-browser:list-extensions');
  },
  loadUnpackedExtension() {
    return ipcRenderer.invoke('paw-browser:load-extension');
  },
  openExtensionsFolder() {
    return ipcRenderer.invoke('paw-browser:open-extensions-folder');
  },
  openDownloads() {
    return ipcRenderer.invoke('paw-browser:open-downloads');
  },
  pickWorkspaceDirectory() {
    return ipcRenderer.invoke('paw-host:pick-workspace-directory');
  },
  register(tab) {
    ipcRenderer.send('paw-browser:register', tab);
  },
  removeHistoryEntry(entryId) {
    return ipcRenderer.invoke('paw-browser:remove-history-entry', entryId);
  },
  removeExtension(extensionId) {
    return ipcRenderer.invoke('paw-browser:remove-extension', extensionId);
  },
  setStartPage(startPage) {
    return ipcRenderer.invoke('paw-browser:set-start-page', startPage);
  },
  takeScreenshot(webContentsId) {
    return ipcRenderer.invoke('paw-browser:take-screenshot', webContentsId);
  },
  onCommand(listener) {
    const handler = (_event, command) => listener(command);
    ipcRenderer.on('paw-browser:command', handler);
    return () => ipcRenderer.off('paw-browser:command', handler);
  },
  onGuestClosed(listener) {
    const handler = (_event, tabId) => listener(tabId);
    ipcRenderer.on('paw-browser:guest-closed', handler);
    return () => ipcRenderer.off('paw-browser:guest-closed', handler);
  },
  onHistoryChanged(listener) {
    const handler = (_event, history) => listener(history);
    ipcRenderer.on('paw-browser:history-updated', handler);
    return () => ipcRenderer.off('paw-browser:history-updated', handler);
  },
  onOpenUrl(listener) {
    const handler = (_event, url) => listener(url);
    ipcRenderer.on('paw-browser:open-url', handler);
    return () => ipcRenderer.off('paw-browser:open-url', handler);
  },
  onSelectTab(listener) {
    const handler = (_event, tabId) => listener(tabId);
    ipcRenderer.on('paw-browser:select-tab', handler);
    return () => ipcRenderer.off('paw-browser:select-tab', handler);
  },
}));
