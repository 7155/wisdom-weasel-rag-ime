import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  CircleAlert,
  CircleX,
  Camera,
  Download,
  EllipsisVertical,
  Globe2,
  History,
  Home,
  PanelRightClose,
  PanelRightOpen,
  Printer,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Square,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type WheelEvent } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { BrowserFindBar, type BrowserFindMatch } from '@/features/browser/BrowserFindBar';
import { BrowserOmnibox } from '@/features/browser/BrowserOmnibox';
import { BrowserPageStatus } from '@/features/browser/BrowserPageStatus';
import { BrowserTabStrip, type BrowserTabItem } from '@/features/browser/BrowserTabStrip';
import {
  PAW_BROWSER_PARTITION,
  guestNavigationState,
  loadPawBrowserUrl,
  pawBrowserHost,
  type PawBrowserGuestFailLoadEvent,
  type PawBrowserGuestFaviconEvent,
  type PawBrowserGuestFoundInPageEvent,
  type PawBrowserGuestProcessGoneEvent,
  type PawBrowserHistoryEntry,
  type PawBrowserWebview,
  type PawBrowserSettings,
} from './paw-browser-host';
import {
  browserActionLabel,
  browserElement,
  errorText,
  formatBytes,
  historyClock,
  historyDateTime,
  historyDayKey,
  historyDayLabel,
  hostTab,
  initialHostTab,
  isTextEntry,
  knownCount,
  normalizedAddress,
  number,
  record,
  rows,
  text,
  type BrowserElement,
  type BrowserRecord,
  type HostBrowserTab,
} from './paw-browser-model';
import { PawWindowChromePortal, usePawWindowChromeTarget } from '../shell/PawWindowChrome';
import type { PawOsWindowTarget } from '@/features/paw-os/model/desktop';

export function PawBrowserApp({ target }: { target?: Extract<PawOsWindowTarget, { kind: 'browser-target' }> } = {}) {
  const transport = useControlTransport();
  const electronHost = pawBrowserHost();
  const windowChromeTarget = usePawWindowChromeTarget();
  const [tabs, setTabs] = useState<BrowserRecord[]>([]);
  const [traces, setTraces] = useState<BrowserRecord[]>([]);
  const [snapshot, setSnapshot] = useState<BrowserRecord>({});
  const [selectedTabId, setSelectedTabId] = useState(0);
  const [address, setAddress] = useState('');
  const [currentUrl, setCurrentUrl] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [showTrace, setShowTrace] = useState(false);
  const [editingElement, setEditingElement] = useState<BrowserElement | null>(null);
  const [elementDraft, setElementDraft] = useState('');
  const [hostTabs, setHostTabs] = useState<HostBrowserTab[]>([initialHostTab()]);
  const [selectedHostTabId, setSelectedHostTabId] = useState('paw-tab-1');
  const [history, setHistory] = useState<PawBrowserHistoryEntry[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [historyQuery, setHistoryQuery] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [browserSettings, setBrowserSettings] = useState<PawBrowserSettings | null>(null);
  const [settingsReceipt, setSettingsReceipt] = useState('');
  const [startPageDraft, setStartPageDraft] = useState('about:blank');
  const [showBrowserMenu, setShowBrowserMenu] = useState(false);
  const [showFind, setShowFind] = useState(false);
  const [findDraft, setFindDraft] = useState('');
  const [findMatch, setFindMatch] = useState<BrowserFindMatch>(null);
  const [zoomPercent, setZoomPercent] = useState(100);
  const [browserActionReceipt, setBrowserActionReceipt] = useState('');
  const [confirmingClear, setConfirmingClear] = useState<'' | 'history' | 'cache' | 'site-data'>('');
  const hostWebviews = useRef(new Map<string, PawBrowserWebview>());
  const started = useRef(false);
  const openedTargetCommand = useRef('');
  const appliedTargetSelection = useRef('');
  const selectedTab = tabs.find((tab) => number(tab.tabId) === selectedTabId) ?? tabs[0];
  const selectedHostTab = hostTabs.find((tab) => tab.id === selectedHostTabId) ?? hostTabs[0];
  const selectedTabUrl = electronHost ? selectedHostTab?.url ?? 'about:blank' : text(selectedTab?.url);

  const refreshShell = useCallback(async () => {
    const [tabsValue, tracesValue] = await Promise.all([
      transport.request({ pathId: 'browser.tabs' }),
      transport.request({ pathId: 'browser.traces', query: { limit: 30 } }),
    ]);
    const nextTabs = rows(record(tabsValue).items);
    const nextTraces = rows(record(tracesValue).items);
    setTabs(nextTabs);
    setTraces(nextTraces);
    const selectedStillExists = selectedTabId > 0
      && nextTabs.some((tab) => number(tab.tabId) === selectedTabId);
    const nextTabId = selectedStillExists ? selectedTabId : number(nextTabs[0]?.tabId);
    const nextTab = nextTabs.find((tab) => number(tab.tabId) === nextTabId) ?? nextTabs[0];
    if (nextTabId && nextTabId !== selectedTabId) setSelectedTabId(nextTabId);
    if (nextTabId && text(nextTab?.url) && text(nextTab?.url) !== 'about:blank' && nextTraces.some((trace) => (
      text(trace.sourceKind) === 'agent'
        && ['queued', 'claimed'].includes(text(trace.status))
    ))) {
      const liveSnapshot = record(await transport.request({
        pathId: 'browser.snapshot.latest',
        query: { deviceId: 'paw-browser', tabId: nextTabId, includeMarkdown: true },
      }));
      if (liveSnapshot.snapshotId) setSnapshot(liveSnapshot);
    }
  }, [selectedTabId, transport]);

  const captureSnapshot = useCallback(async (tabId: number) => {
    if (!tabId) return;
    try {
      const captured = record(await transport.request({
        pathId: 'browser.command',
        body: { action: 'screenshot', deviceId: 'paw-browser', tabId },
      }));
      if (captured.ok === false) throw new Error(text(captured.summary) || '页面没有打开');
      const value = record(await transport.request({
        pathId: 'browser.snapshot.latest',
        query: { deviceId: 'paw-browser', tabId, includeMarkdown: true },
      }));
      setSnapshot(value);
      const url = text(value.url);
      if (url) {
        setAddress(url);
        setCurrentUrl(url);
      }
      setError('');
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }, [transport]);

  useEffect(() => {
    let active = true;
    async function boot() {
      try {
        if (!started.current) {
          started.current = true;
          if (!electronHost) await transport.request({ pathId: 'browser.managed.start', body: {} });
        }
        if (active) await refreshShell();
      } catch (requestError) {
        if (active) setError(errorText(requestError));
      }
    }
    void boot();
    const timer = window.setInterval(() => { if (active) void refreshShell().catch(() => undefined); }, 1_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [electronHost, refreshShell, transport]);

  useEffect(() => {
    const url = target?.url?.trim() ?? '';
    const key = `${target?.commandId ?? ''}\n${url}`;
    if (!electronHost || !url || openedTargetCommand.current === key) return;
    openedTargetCommand.current = key;
    const tab = hostTab(url, target?.commandId);
    setHostTabs((current) => [...current, tab]);
    setSelectedHostTabId(tab.id);
  }, [electronHost, target?.commandId, target?.url]);

  useEffect(() => electronHost?.onGuestClosed((tabId) => closeHostTab(tabId)), [electronHost, selectedHostTabId]);
  useEffect(() => electronHost?.onHistoryChanged(setHistory), [electronHost]);
  useEffect(() => electronHost?.onSelectTab((tabId) => setSelectedHostTabId(tabId)), [electronHost]);

  useEffect(() => {
    if (!target) return;
    const targetKey = [
      target.commandId ?? '',
      target.targetId,
      target.tabId ?? '',
      target.url ?? '',
    ].join('\n');
    if (appliedTargetSelection.current === targetKey) return;
    if (electronHost) {
      const hostTab = hostTabs.find((tab) => (
        (target.commandId && tab.commandId === target.commandId)
        || tab.id === target.targetId
      ));
      if (!hostTab) return;
      appliedTargetSelection.current = targetKey;
      if (hostTab.id !== selectedHostTabId) setSelectedHostTabId(hostTab.id);
      return;
    }
    const tab = tabs.find((candidate) => (
      text(candidate.targetId) === target.targetId
      || (target.tabId !== undefined && number(candidate.tabId) === target.tabId)
    ));
    const tabId = number(tab?.tabId);
    if (!tabId) return;
    appliedTargetSelection.current = targetKey;
    if (tabId !== selectedTabId) setSelectedTabId(tabId);
  }, [electronHost, hostTabs, selectedHostTabId, selectedTabId, tabs, target]);

  useEffect(() => {
    if (!electronHost || !selectedHostTab) return;
    const selectedUrl = selectedHostTab.url || 'about:blank';
    setAddress(selectedUrl === 'about:blank' ? '' : selectedUrl);
    setCurrentUrl(selectedUrl);
    if (selectedHostTab.webContentsId) {
      electronHost.activate({
        title: selectedHostTab.title,
        url: selectedUrl,
        webContentsId: selectedHostTab.webContentsId,
      });
    }
  }, [electronHost, selectedHostTab]);

  // Find state and zoom are per-guest: switching tabs drops the stale query
  // and reads the real zoom factor of the newly selected guest.
  useEffect(() => {
    if (!electronHost) return;
    setShowFind(false);
    setFindDraft('');
    setFindMatch(null);
    const webview = hostWebviews.current.get(selectedHostTabId);
    const factor = typeof webview?.getZoomFactor === 'function' ? webview.getZoomFactor() : null;
    setZoomPercent(typeof factor === 'number' && Number.isFinite(factor) ? Math.round(factor * 100) : 100);
  }, [electronHost, selectedHostTabId]);

  useEffect(() => {
    if (!browserActionReceipt) return;
    const timer = window.setTimeout(() => setBrowserActionReceipt(''), 6_000);
    return () => window.clearTimeout(timer);
  }, [browserActionReceipt]);

  // A pending destructive confirmation never outlives its surface.
  useEffect(() => {
    if (!showHistory && !showSettings) setConfirmingClear('');
  }, [showHistory, showSettings]);

  const refreshBrowserHistory = useCallback(async () => {
    if (!electronHost) return;
    setHistory(await electronHost.getHistory());
  }, [electronHost]);

  const refreshBrowserSettings = useCallback(async () => {
    if (!electronHost) return;
    const value = await electronHost.getSettings();
    setBrowserSettings(value);
    setStartPageDraft(value.startPage);
  }, [electronHost]);

  useEffect(() => {
    if (!electronHost) return;
    void refreshBrowserSettings().then(() => undefined, (requestError) => setError(errorText(requestError)));
    void refreshBrowserHistory().then(() => undefined, (requestError) => setError(errorText(requestError)));
  }, [electronHost, refreshBrowserHistory, refreshBrowserSettings]);

  useEffect(() => {
    if (!electronHost || !browserSettings || browserSettings.startPage === 'about:blank') return;
    const firstTab = hostTabs.length === 1 ? hostTabs[0] : null;
    if (!firstTab || firstTab.url !== 'about:blank') return;
    loadPawBrowserUrl({ current: hostWebviews.current.get(firstTab.id) ?? null }, browserSettings.startPage);
    updateHostTab(firstTab.id, { title: browserSettings.startPage, url: browserSettings.startPage });
  }, [browserSettings, electronHost, hostTabs]);

  useEffect(() => {
    if (electronHost) return;
    if (!selectedTabId) return;
    if (!selectedTabUrl || selectedTabUrl === 'about:blank') {
      setSnapshot({});
      setAddress('');
      setCurrentUrl('about:blank');
      setError('');
      return;
    }
    setAddress(selectedTabUrl);
    setCurrentUrl(selectedTabUrl);
    void captureSnapshot(selectedTabId);
  }, [captureSnapshot, electronHost, selectedTabId, selectedTabUrl]);

  const run = useCallback(async (action: string, extra: BrowserRecord = {}) => {
    setBusy(action);
    setError('');
    try {
      const value = record(await transport.request({
        pathId: 'browser.command',
        body: {
          action,
          deviceId: 'paw-browser',
          ...(selectedTabId ? { tabId: selectedTabId } : {}),
          ...extra,
        },
      }));
      if (value.ok === false) throw new Error(text(value.summary) || '浏览器操作未完成');
      await refreshShell();
      const result = record(value.result);
      const nextTabId = number(result.tabId) || selectedTabId;
      if (action === 'new_tab' && nextTabId) {
        setSelectedTabId(nextTabId);
        const nextUrl = text(extra.url) || 'about:blank';
        setAddress(nextUrl === 'about:blank' ? '' : nextUrl);
        setCurrentUrl(nextUrl);
      } else if (nextTabId && action !== 'close_tab' && text(result.url) !== 'about:blank') {
        await captureSnapshot(nextTabId);
      }
      return value;
    } catch (requestError) {
      setError(errorText(requestError));
      throw requestError;
    } finally {
      setBusy('');
    }
  }, [captureSnapshot, refreshShell, selectedTabId, transport]);

  const navigateTo = (rawUrl: string) => {
    const url = normalizedAddress(rawUrl);
    if (!url) return;
    setAddress(url);
    setCurrentUrl(url);
    if (electronHost && selectedHostTab) {
      loadPawBrowserUrl(
        { current: hostWebviews.current.get(selectedHostTab.id) ?? null },
        url,
      );
      updateHostTab(selectedHostTab.id, { url });
      return;
    }
    if (selectedTabId && !busy) {
      void run('navigate', { url });
    }
  };

  const updateHostTab = (tabId: string, update: Partial<HostBrowserTab>) => {
    setHostTabs((current) => current.map((tab) => tab.id === tabId ? { ...tab, ...update } : tab));
  };

  const addHostTab = (url = 'about:blank') => {
    const tab = hostTab(url);
    setHostTabs((current) => [...current, tab]);
    setSelectedHostTabId(tab.id);
    setAddress(url === 'about:blank' ? '' : url);
    setCurrentUrl(url);
  };

  const closeHostTab = (tabId: string) => {
    setHostTabs((current) => {
      const index = current.findIndex((tab) => tab.id === tabId);
      const next = current.filter((tab) => tab.id !== tabId);
      if (next.length === 0) {
        const blank = initialHostTab();
        setSelectedHostTabId(blank.id);
        return [blank];
      }
      if (tabId === selectedHostTabId) {
        setSelectedHostTabId(next[Math.min(Math.max(index, 0), next.length - 1)].id);
      }
      return next;
    });
  };

  const runNavigation = (action: 'back' | 'forward' | 'reload') => {
    const webview = selectedHostTab ? hostWebviews.current.get(selectedHostTab.id) : null;
    if (electronHost && webview) {
      if (action === 'back' && webview.canGoBack()) webview.goBack();
      if (action === 'forward' && webview.canGoForward()) webview.goForward();
      if (action === 'reload') webview.reload();
      return;
    }
    void run(action);
  };

  const isStartPage = !currentUrl || currentUrl === 'about:blank' || currentUrl === 'paw://home';
  const snapshotId = text(snapshot.snapshotId);
  const snapshotImageUrl = snapshotId && snapshot.hasScreenshot && transport.browserSnapshotImageUrl
    ? transport.browserSnapshotImageUrl(snapshotId)
    : '';
  const viewport = record(snapshot.viewport);
  const viewportWidth = number(viewport.width);
  const viewportHeight = number(viewport.height);
  const elements = rows(viewport.elements).map(browserElement).filter((item): item is BrowserElement => Boolean(item));
  const activeAgentTrace = traces.find((trace) => (
    text(trace.sourceKind) === 'agent'
      && ['queued', 'claimed'].includes(text(trace.status))
  ));
  const latestAgentTrace = activeAgentTrace ?? traces.find((trace) => (
    text(trace.sourceKind) === 'agent'
      && Date.now() - (number(trace.completedAtMs) || number(trace.createdAtMs)) < 3_000
  ));
  const latestAgentSteps = rows(latestAgentTrace?.steps);
  const latestAgentStep = latestAgentSteps.at(-1);
  const latestAgentAction = text(latestAgentStep?.action) || text(latestAgentTrace?.action);
  const latestAgentTask = text(latestAgentTrace?.target)
    || text(record(latestAgentTrace?.result).summary)
    || text(selectedTab?.title)
    || selectedHostTab?.title
    || '当前页面';
  const latestAgentTarget = text(latestAgentStep?.target) || latestAgentTask;
  const agentExecutionState = activeAgentTrace ? 'active' : latestAgentTrace ? 'settled' : '';
  const agentTargetRefId = text(latestAgentTrace?.targetRefId);
  const activateElement = (element: BrowserElement) => {
    if (isTextEntry(element)) {
      setEditingElement(element);
      setElementDraft('');
      return;
    }
    void run('click', { refId: element.refId });
  };

  const submitElementDraft = () => {
    if (!editingElement || busy) return;
    const target = editingElement;
    const value = elementDraft;
    setEditingElement(null);
    setElementDraft('');
    void run('type', { refId: target.refId, text: value, clear: true, submit: true });
  };

  const scrollPage = (event: WheelEvent<HTMLDivElement>) => {
    if (busy || Math.abs(event.deltaY) < 8) return;
    event.preventDefault();
    void run('scroll', {
      direction: event.deltaY < 0 ? 'up' : 'down',
      amount: Math.min(1_200, Math.max(160, Math.round(Math.abs(event.deltaY) * 2))),
    });
  };

  const stopAgentBrowserWork = async () => {
    setBusy('stop');
    try {
      await transport.request({ pathId: 'browser.stop', body: {} });
      await refreshShell();
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setBusy('');
    }
  };

  const clearBrowserData = async (action: 'cache' | 'site-data') => {
    if (!electronHost) return;
    setConfirmingClear('');
    setBusy(`clear-${action}`);
    setSettingsReceipt('');
    try {
      const receipt = await electronHost.clearBrowsingData(action);
      setSettingsReceipt(action === 'cache'
        ? `缓存已清除（${formatBytes(receipt.before)} → ${formatBytes(receipt.after)}）`
        : `Cookie 与站点数据已清除（${receipt.before} → ${receipt.after}）`);
      await refreshBrowserSettings();
    } catch (requestError) {
      setSettingsReceipt(`清理失败：${errorText(requestError)}`);
    } finally {
      setBusy('');
    }
  };

  const saveStartPage = async () => {
    if (!electronHost) return;
    setBusy('save-start-page');
    setSettingsReceipt('');
    try {
      const saved = await electronHost.setStartPage(normalizedAddress(startPageDraft) || 'about:blank');
      setStartPageDraft(saved.startPage);
      setSettingsReceipt('启动页已保存');
      await refreshBrowserSettings();
    } catch (requestError) {
      setSettingsReceipt(`保存失败：${errorText(requestError)}`);
    } finally {
      setBusy('');
    }
  };

  const selectedWebview = () => selectedHostTab ? hostWebviews.current.get(selectedHostTab.id) ?? null : null;

  const takeOverBrowserWork = async () => {
    await stopAgentBrowserWork();
    setShowTrace(false);
    selectedWebview()?.focus();
  };

  const findOnPage = (value: string, findNext = false, forward = true) => {
    setFindDraft(value);
    if (!value) {
      selectedWebview()?.stopFindInPage('clearSelection');
      setFindMatch(null);
      return;
    }
    selectedWebview()?.findInPage(value, { findNext, forward });
  };

  const closeFind = () => {
    selectedWebview()?.stopFindInPage('clearSelection');
    setFindDraft('');
    setFindMatch(null);
    setShowFind(false);
    selectedWebview()?.focus();
  };

  const applyZoomPercent = (next: number) => {
    const webview = selectedWebview();
    if (!webview) return;
    webview.setZoomFactor(next / 100);
    setZoomPercent(next);
  };

  const changeZoom = (step: number) => {
    applyZoomPercent(Math.min(300, Math.max(25, zoomPercent + step)));
  };

  const takeScreenshot = async () => {
    if (!electronHost || !selectedHostTab?.webContentsId) return;
    setBusy('screenshot');
    try {
      const receipt = await electronHost.takeScreenshot(selectedHostTab.webContentsId);
      setBrowserActionReceipt(receipt.saved ? `截图已保存到 ${receipt.path}` : '截图未保存');
    } catch (requestError) {
      setBrowserActionReceipt(`截图失败：${errorText(requestError)}`);
    } finally {
      setBusy('');
      setShowBrowserMenu(false);
    }
  };

  const openDownloads = async () => {
    if (!electronHost) return;
    try {
      const receipt = await electronHost.openDownloads();
      setBrowserActionReceipt(receipt.opened ? `已打开下载目录 ${receipt.path}` : '下载目录未打开');
    } catch (requestError) {
      setBrowserActionReceipt(`打开下载目录失败：${errorText(requestError)}`);
    } finally {
      setShowBrowserMenu(false);
    }
  };

  const clearHistory = async () => {
    if (!electronHost) return;
    setConfirmingClear('');
    setBusy('clear-history');
    try {
      setHistory(await electronHost.clearHistory());
      setBrowserActionReceipt('浏览历史已清空');
    } catch (requestError) {
      setBrowserActionReceipt(`清空浏览历史失败：${errorText(requestError)}`);
    } finally {
      setBusy('');
    }
  };

  const removeHistoryEntry = async (entryId: string) => {
    if (!electronHost) return;
    try {
      setHistory(await electronHost.removeHistoryEntry(entryId));
    } catch (requestError) {
      setBrowserActionReceipt(`删除浏览记录失败：${errorText(requestError)}`);
    }
  };

  const retryPage = () => {
    const webview = selectedWebview();
    const tab = selectedHostTab;
    if (!webview || !tab) return;
    const failedUrl = tab.failure?.url;
    updateHostTab(tab.id, { crashedReason: undefined, failure: null, loading: true });
    if (failedUrl) void webview.loadURL(failedUrl);
    else webview.reload();
  };

  const visibleHistory = useMemo(() => history.filter((entry) => {
    const query = historyQuery.trim().toLocaleLowerCase();
    return !query || entry.title.toLocaleLowerCase().includes(query) || entry.url.toLocaleLowerCase().includes(query);
  }), [history, historyQuery]);

  // History reads like a timeline: consecutive visits of the same calendar day
  // share one day heading, and rows only repeat the clock time.
  const historyDayGroups = useMemo(() => {
    const groups: { key: string; label: string; entries: PawBrowserHistoryEntry[] }[] = [];
    for (const entry of visibleHistory) {
      const key = historyDayKey(entry.visitedAt);
      const lastGroup = groups.at(-1);
      if (lastGroup && lastGroup.key === key) lastGroup.entries.push(entry);
      else groups.push({ key, label: historyDayLabel(entry.visitedAt), entries: [entry] });
    }
    return groups;
  }, [visibleHistory]);

  const homePage = electronHost ? (browserSettings?.startPage || 'about:blank') : 'about:blank';

  const selectedTabLoading = Boolean(electronHost && selectedHostTab?.loading);
  const selectedPageFailure = electronHost ? selectedHostTab?.failure ?? null : null;
  const selectedPageCrash = electronHost ? selectedHostTab?.crashedReason : undefined;
  const tabItems: BrowserTabItem[] = electronHost
    ? hostTabs.map((tab) => ({
      id: tab.id,
      title: tab.title || '新标签页',
      active: tab.id === selectedHostTabId,
      loading: tab.loading,
      favicon: tab.favicon,
      failed: Boolean(tab.failure || tab.crashedReason),
    }))
    : tabs.map((tab) => ({
      id: String(number(tab.tabId)),
      title: text(tab.title) || '新标签页',
      active: number(tab.tabId) === selectedTabId,
      loading: Boolean(tab.loading) || undefined,
      favicon: text(tab.favicon) || undefined,
    }));

  const browserTabs = (
    <BrowserTabStrip
      inWindowChrome={Boolean(windowChromeTarget)}
      newTabDisabled={Boolean(busy)}
      onClose={(tabId) => {
        if (electronHost) closeHostTab(tabId);
        else void run('close_tab');
      }}
      onNewTab={() => {
        if (electronHost) addHostTab();
        else void run('new_tab', { url: 'about:blank' });
      }}
      onSelect={(tabId) => {
        if (electronHost) setSelectedHostTabId(tabId);
        else setSelectedTabId(Number(tabId));
      }}
      tabs={tabItems}
    />
  );

  return (
    <>
      {windowChromeTarget ? <PawWindowChromePortal>{browserTabs}</PawWindowChromePortal> : null}
      <main className="paw-direct-browser" data-tabs-in-window-chrome={windowChromeTarget ? true : undefined}>
        {windowChromeTarget ? null : browserTabs}

      <section className="paw-browser-toolbar">
        <div className="paw-nav-buttons">
          <button
            aria-label="后退"
            disabled={electronHost ? !selectedHostTab?.canGoBack : !selectedTabId || Boolean(busy)}
            onClick={() => runNavigation('back')}
            type="button"
          >
            <ArrowLeft size={15} />
          </button>
          <button
            aria-label="前进"
            disabled={electronHost ? !selectedHostTab?.canGoForward : !selectedTabId || Boolean(busy)}
            onClick={() => runNavigation('forward')}
            type="button"
          >
            <ArrowRight size={15} />
          </button>
          <button
            aria-label={selectedTabLoading ? '停止加载' : '刷新网页'}
            disabled={electronHost ? !selectedHostTab : !selectedTabId || Boolean(busy)}
            onClick={() => {
              if (selectedTabLoading) selectedWebview()?.stop();
              else runNavigation('reload');
            }}
            type="button"
          >
            {selectedTabLoading ? <X size={14} /> : <RefreshCw className={busy === 'reload' ? 'ui-spin' : ''} size={14} />}
          </button>
          <button
            aria-label={homePage === 'about:blank' ? '打开空白页' : '打开启动页'}
            className="paw-browser-home"
            onClick={() => navigateTo(homePage)}
            title={homePage === 'about:blank' ? '打开空白页' : `打开启动页 ${homePage}`}
            type="button"
          >
            <Home size={14} />
          </button>
        </div>

        <BrowserOmnibox
          address={address}
          currentUrl={currentUrl}
          onAddressChange={setAddress}
          onNavigate={navigateTo}
        />

        <div className="paw-toolbar-actions">
          <button
            aria-label={showTrace ? '隐藏 Agent 浏览器轨迹' : '显示 Agent 浏览器轨迹'}
            aria-pressed={showTrace}
            data-active={showTrace || undefined}
            onClick={() => setShowTrace((value) => !value)}
            title="Agent 浏览器轨迹"
            type="button"
          >
            {showTrace ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
          </button>
          <button
            aria-label="浏览历史"
            className="paw-browser-history-toggle"
            disabled={Boolean(busy)}
            onClick={() => { setShowSettings(false); setShowHistory((value) => !value); }}
            title="浏览历史"
            type="button"
          >
            <History size={14} />
          </button>
          <button
            aria-label="Browser 设置"
            className="paw-browser-settings-toggle"
            disabled={!electronHost || Boolean(busy)}
            onClick={() => { setShowHistory(false); setShowSettings((value) => !value); if (!showSettings) void refreshBrowserSettings(); }}
            title={electronHost ? 'Browser 设置' : 'Browser 设置需要 PAWOS 桌面版宿主'}
            type="button"
          >
            <Settings size={14} />
          </button>
          <button
            aria-expanded={showBrowserMenu}
            aria-haspopup="menu"
            aria-label="Browser 菜单"
            disabled={!electronHost || Boolean(busy)}
            onClick={() => {
              const next = !showBrowserMenu;
              if (next) {
                const factor = selectedWebview()?.getZoomFactor?.();
                if (typeof factor === 'number') setZoomPercent(Math.round(factor * 100));
              }
              setShowBrowserMenu(next);
            }}
            title={electronHost ? 'Browser 菜单' : '页内查找、打印、缩放等操作需要 PAWOS 桌面版宿主'}
            type="button"
          >
            <EllipsisVertical size={14} />
          </button>
          {electronHost && showBrowserMenu ? (
            <div className="paw-browser-menu" role="menu">
              <button onClick={() => { setShowFind(true); setShowBrowserMenu(false); }} role="menuitem" type="button"><Search size={13} />页内查找</button>
              <button onClick={() => { selectedWebview()?.print(); setShowBrowserMenu(false); }} role="menuitem" type="button"><Printer size={13} />打印</button>
              <div className="paw-browser-menu-zoom">
                <span>缩放</span>
                <button aria-label="缩小网页" onClick={() => changeZoom(-10)} type="button"><ZoomOut size={13} /></button>
                <button
                  aria-label="恢复默认缩放"
                  className="paw-browser-menu-zoom-reset"
                  disabled={zoomPercent === 100}
                  onClick={() => applyZoomPercent(100)}
                  title={zoomPercent === 100 ? '当前为默认缩放' : '恢复 100%'}
                  type="button"
                >
                  {zoomPercent}%
                </button>
                <button aria-label="放大网页" onClick={() => changeZoom(10)} type="button"><ZoomIn size={13} /></button>
              </div>
              <button onClick={() => void takeScreenshot()} role="menuitem" type="button"><Camera size={13} />截图</button>
              <button onClick={() => void openDownloads()} role="menuitem" type="button"><Download size={13} />下载</button>
              <button className="paw-browser-menu-narrow-only" onClick={() => { setShowSettings(false); setShowHistory(true); setShowBrowserMenu(false); void refreshBrowserHistory(); }} role="menuitem" type="button"><History size={13} />浏览历史</button>
              <button className="paw-browser-menu-narrow-only" onClick={() => { setShowHistory(false); setShowSettings(true); setShowBrowserMenu(false); void refreshBrowserSettings(); }} role="menuitem" type="button"><Settings size={13} />浏览器设置</button>
            </div>
          ) : null}
        </div>
      </section>

      <section className="paw-browser-workspace" data-show-agent={showTrace || undefined}>
        <div className="paw-browser-viewport" data-agent-state={agentExecutionState || undefined}>
          {electronHost && showFind ? (
            <BrowserFindBar
              match={findMatch}
              onChange={(value) => findOnPage(value)}
              onClose={closeFind}
              onNext={() => findOnPage(findDraft, true, true)}
              onPrevious={() => findOnPage(findDraft, true, false)}
              value={findDraft}
            />
          ) : null}
          {browserActionReceipt ? (
            <div className="paw-browser-action-receipt">
              <output role="status">{browserActionReceipt}</output>
              <button aria-label="关闭操作提示" onClick={() => setBrowserActionReceipt('')} type="button"><X size={12} /></button>
            </div>
          ) : null}
          {showHistory ? (
            <section aria-label="浏览历史" className="paw-browser-history">
              <div className="paw-browser-surface-card">
                <header>
                  <div><History size={16} /><strong>浏览历史</strong></div>
                  <div>
                    {confirmingClear === 'history' ? (
                      <span aria-label="确认清空浏览历史" className="paw-browser-confirm" role="group">
                        <em>清空全部浏览历史？</em>
                        <button data-danger disabled={Boolean(busy)} onClick={() => void clearHistory()} type="button">确认清空</button>
                        <button onClick={() => setConfirmingClear('')} type="button">取消</button>
                      </span>
                    ) : (
                      <button disabled={!history.length || Boolean(busy)} onClick={() => setConfirmingClear('history')} type="button">清空</button>
                    )}
                    <button aria-label="关闭浏览历史" onClick={() => setShowHistory(false)} type="button"><X size={14} /></button>
                  </div>
                </header>
                <label className="paw-browser-history-search"><Search size={13} /><input aria-label="搜索浏览历史" onChange={(event) => setHistoryQuery(event.target.value)} placeholder="搜索标题或网址" type="search" value={historyQuery} /></label>
                {historyDayGroups.length ? (
                  <div className="paw-browser-history-days">
                    {historyDayGroups.map((group) => (
                      <section className="paw-browser-history-day" key={group.key}>
                        <h3>{group.label}</h3>
                        <ol>
                          {group.entries.map((entry) => (
                            <li key={`${entry.visitedAt}-${entry.url}`}>
                              <button onClick={() => { setShowHistory(false); navigateTo(entry.url); }} type="button">
                                <Globe2 size={14} />
                                <span><strong>{entry.title || entry.url}</strong><small>{entry.url}</small></span>
                                <time dateTime={historyDateTime(entry.visitedAt)}>{historyClock(entry.visitedAt)}</time>
                              </button>
                              <button aria-label={`删除 ${entry.title || entry.url}`} onClick={() => void removeHistoryEntry(entry.id)} type="button"><X size={13} /></button>
                            </li>
                          ))}
                        </ol>
                      </section>
                    ))}
                  </div>
                ) : <p>{history.length ? '没有匹配的浏览记录' : '还没有浏览记录'}</p>}
              </div>
            </section>
          ) : null}
          {electronHost && showSettings ? (
            <section aria-label="Browser 设置" className="paw-browser-settings">
              <div className="paw-browser-surface-card">
                <header><div><Settings size={16} /><strong>Browser 设置</strong></div><button aria-label="关闭 Browser 设置" onClick={() => setShowSettings(false)} type="button"><X size={14} /></button></header>
                <div className="paw-browser-settings-body">
                  <section><h3>启动页</h3><div className="paw-browser-setting-row"><input aria-label="Browser 启动页" onChange={(event) => setStartPageDraft(event.target.value)} value={startPageDraft} /><button disabled={Boolean(busy)} onClick={() => void saveStartPage()} type="button">保存</button></div></section>
                  <section><h3>下载</h3><p>下载位置</p><code>{browserSettings?.downloadPath || '读取中…'}</code></section>
                  <section>
                    <h3>浏览数据</h3>
                    <div className="paw-browser-setting-row">
                      <span>缓存 · {formatBytes(browserSettings?.cacheBytes ?? 0)}</span>
                      {confirmingClear === 'cache' ? (
                        <span aria-label="确认清除缓存" className="paw-browser-confirm" role="group">
                          <button data-danger disabled={Boolean(busy)} onClick={() => void clearBrowserData('cache')} type="button">确认清除</button>
                          <button onClick={() => setConfirmingClear('')} type="button">取消</button>
                        </span>
                      ) : (
                        <button disabled={Boolean(busy)} onClick={() => setConfirmingClear('cache')} type="button">清除缓存</button>
                      )}
                    </div>
                    <div className="paw-browser-setting-row">
                      <span>Cookie 与站点数据 · {browserSettings?.cookieCount ?? 0} 个 Cookie</span>
                      {confirmingClear === 'site-data' ? (
                        <span aria-label="确认清除 Cookie 与站点数据" className="paw-browser-confirm" role="group">
                          <button data-danger disabled={Boolean(busy)} onClick={() => void clearBrowserData('site-data')} type="button">确认清除</button>
                          <button onClick={() => setConfirmingClear('')} type="button">取消</button>
                        </span>
                      ) : (
                        <button disabled={Boolean(busy)} onClick={() => setConfirmingClear('site-data')} type="button">清除 Cookie 与站点数据</button>
                      )}
                    </div>
                  </section>
                  <section><h3>网站权限</h3><p>网站在需要时请求权限，由当前隔离 Browser Session 处理。</p></section>
                  {settingsReceipt ? <output role="status">{settingsReceipt}</output> : null}
                </div>
              </div>
            </section>
          ) : null}
          {electronHost ? hostTabs.map((tab) => (
            <NativeBrowserWebview
              active={tab.id === selectedHostTabId}
              key={tab.id}
              onChange={({ title, url, webContentsId }) => {
                updateHostTab(tab.id, { title, url });
                if (tab.id === selectedHostTabId) {
                  setAddress(url === 'about:blank' ? '' : url);
                  setCurrentUrl(url);
                  electronHost.activate({ title, url, webContentsId });
                }
              }}
              onFoundInPage={(match) => {
                if (tab.id === selectedHostTabId) setFindMatch(match);
              }}
              onGuestState={(update) => updateHostTab(tab.id, update)}
              onIdentity={(webContentsId) => {
                updateHostTab(tab.id, { webContentsId });
                electronHost.register({ commandId: tab.commandId, tabId: tab.id, webContentsId });
              }}
              onWebview={(element) => {
                if (element) hostWebviews.current.set(tab.id, element);
                else hostWebviews.current.delete(tab.id);
              }}
              tab={tab}
            />
          )) : null}
          {electronHost && isStartPage && !selectedPageFailure && !selectedPageCrash ? (
            <div aria-hidden="true" className="paw-browser-start" data-live={activeAgentTrace ? true : undefined}>
              <span className="paw-browser-start-halo"><Globe2 size={26} /></span>
              <strong>新标签页</strong>
              <span className="paw-browser-start-hint">输入网址或搜索内容，回车直达</span>
            </div>
          ) : null}
          {electronHost && (selectedPageFailure || selectedPageCrash) && !showHistory && !showSettings ? (
            <BrowserPageStatus
              crashedReason={selectedPageCrash}
              failure={selectedPageFailure}
              onRetry={retryPage}
            />
          ) : null}
          {!electronHost && error && !isStartPage ? (
            <div className="paw-browser-error" role="alert">
              <CircleAlert size={16} />
              <span><strong>页面没有打开</strong></span>
              <button onClick={() => void refreshShell()} type="button">重试</button>
            </div>
          ) : null}

          {!electronHost && isStartPage ? (
            <div aria-label="空白页面" className="paw-browser-blank-page" />
          ) : !electronHost && snapshotImageUrl && viewportWidth && viewportHeight ? (
            <div className="paw-browser-live-view" onWheel={scrollPage}>
              <div className="paw-browser-live-canvas" style={{ aspectRatio: `${viewportWidth} / ${viewportHeight}` }}>
                <img alt={text(snapshot.title) || '网页视图'} draggable={false} src={snapshotImageUrl} />
                {elements.map((element) => (
                  <button
                    aria-label={element.label || `${element.role} ${element.refId}`}
                    className="paw-browser-hit-target"
                    data-agent-target={agentTargetRefId === element.refId || undefined}
                    key={element.refId}
                    onClick={() => activateElement(element)}
                    style={{
                      height: `${element.height / viewportHeight * 100}%`,
                      left: `${element.x / viewportWidth * 100}%`,
                      top: `${element.y / viewportHeight * 100}%`,
                      width: `${element.width / viewportWidth * 100}%`,
                    }}
                    type="button"
                  />
                ))}
                {editingElement ? (
                  <form
                    className="paw-browser-inline-entry"
                    onSubmit={(event) => { event.preventDefault(); submitElementDraft(); }}
                    style={{
                      left: `${Math.max(0, editingElement.x) / viewportWidth * 100}%`,
                      top: `${Math.max(0, editingElement.y) / viewportHeight * 100}%`,
                      width: `${Math.max(180, editingElement.width) / viewportWidth * 100}%`,
                    }}
                  >
                    <input
                      autoFocus
                      onChange={(event) => setElementDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Escape') {
                          setEditingElement(null);
                          setElementDraft('');
                        }
                      }}
                      placeholder={editingElement.label || '输入'}
                      value={elementDraft}
                    />
                  </form>
                ) : null}
              </div>
            </div>
          ) : !electronHost ? (
            <div className="paw-browser-awaiting">
              <RefreshCw className={busy ? 'ui-spin' : ''} size={18} />
              <button disabled={Boolean(busy)} onClick={() => void captureSnapshot(selectedTabId)} type="button">重新载入</button>
            </div>
          ) : null}

          {latestAgentTrace && !showHistory && !showSettings ? (
            <div className="paw-browser-agent-field" data-state={agentExecutionState}>
              <span aria-hidden="true" className="paw-browser-agent-signal" />
              {activeAgentTrace ? <span aria-hidden="true" className="paw-browser-agent-counter"><Sparkles size={13} />1</span> : null}
              <section aria-label="Agent 浏览器任务" className="paw-browser-agent-capsule">
                <span aria-hidden="true" className="paw-browser-agent-mark"><Sparkles size={17} /></span>
                <output aria-label="Agent 浏览器任务状态" role="status">
                  <strong>{latestAgentTask}</strong>
                  <span><b>{activeAgentTrace ? 'Agent 正在浏览' : 'Agent 刚刚完成'}</b><small><b>{browserActionLabel(latestAgentAction) || '处理页面'}</b><span>{latestAgentTarget}</span></small></span>
                </output>
                <div className="paw-browser-agent-capsule-actions">
                  {activeAgentTrace ? (
                    <>
                      <button aria-label="接管浏览器" onClick={() => void takeOverBrowserWork()} type="button">接管</button>
                      <button aria-label="停止 Agent 浏览器操作" data-danger onClick={() => void stopAgentBrowserWork()} type="button"><Square size={10} />停止</button>
                    </>
                  ) : null}
                </div>
              </section>
            </div>
          ) : null}
        </div>
        {showTrace ? (
          <aside className="paw-browser-agent-stream" aria-label="Agent 浏览器轨迹">
            <header>
              <span><Activity size={13} />Agent 轨迹</span>
              <div>
                {activeAgentTrace ? (
                  <button aria-label="停止 Agent 浏览器操作" onClick={() => void stopAgentBrowserWork()} type="button">
                    <Square size={11} /> 停止
                  </button>
                ) : null}
                <button aria-label="隐藏 Agent 浏览器轨迹" onClick={() => setShowTrace(false)} type="button"><X size={13} /></button>
              </div>
            </header>
            <div>
              {traces.length ? traces.map((trace) => (
                <BrowserTraceRow key={text(trace.commandId)} trace={trace} />
              )) : (
                <div className="paw-browser-no-trace">
                  <Bot size={18} />
                  <strong>暂无操作</strong>
                </div>
              )}
            </div>
            <footer>
              <span data-active={Boolean(activeAgentTrace) || undefined} />
              {activeAgentTrace ? 'Agent 正在操作当前浏览器' : '人和 Agent 共用当前页面'}
            </footer>
          </aside>
        ) : null}
      </section>
      </main>
    </>
  );
}

function BrowserTraceRow({ trace }: { trace: BrowserRecord }) {
  const [showAllSteps, setShowAllSteps] = useState(false);
  const action = text(trace.action);
  const status = text(trace.status);
  const sourceKind = text(trace.sourceKind);
  const target = text(trace.target);
  const result = record(trace.result);
  const steps = rows(trace.steps);
  const latestStep = steps.at(-1);
  const stepPreviewLimit = 4;
  const visibleSteps = showAllSteps ? steps : steps.slice(-stepPreviewLimit);
  const progress = record(trace.progress);
  const totalSteps = knownCount(trace.totalSteps, trace.stepTotal, progress.totalSteps, progress.total);
  const recordedSteps = knownCount(trace.currentStep, trace.completedSteps, progress.currentStep, progress.completed) ?? steps.length;
  const running = ['queued', 'claimed', 'running'].includes(status);
  const displayedAction = text(latestStep?.action) || action;
  const summary = text(latestStep?.error)
    || text(latestStep?.target)
    || text(result.summary)
    || target
    || (sourceKind === 'agent' ? 'PAW Browser' : '手动操作');
  return (
    <article data-source={sourceKind} data-status={status}>
      <span data-status={status}>
        {status === 'completed' ? <Check size={12} /> : status === 'failed' || status === 'cancelled' ? <CircleX size={12} /> : <Bot size={12} />}
      </span>
      <div>
        <strong>{sourceKind === 'agent' ? `Agent · ${browserActionLabel(displayedAction)}` : `你 · ${browserActionLabel(displayedAction)}`}</strong>
        <small>{summary}</small>
        {visibleSteps.length ? (
          <div className="paw-browser-trace-step-window">
            <div className="paw-browser-trace-step-window__meta">
              <span>{showAllSteps ? `已显示 ${steps.length} / 已加载 ${steps.length} 个步骤` : `最近 ${visibleSteps.length} / 已加载 ${steps.length} 个步骤`}</span>
              {running && totalSteps !== null && totalSteps > 0 ? (
                <span className="paw-browser-trace-progress">
                  <progress aria-label="浏览器执行进度" max={totalSteps} value={Math.min(recordedSteps, totalSteps)} />
                  已记录 {Math.min(recordedSteps, totalSteps)} / 共 {totalSteps} 步
                </span>
              ) : running ? <span>总步数未提供</span> : null}
            </div>
            <ol className="paw-browser-trace-steps">
              {visibleSteps.map((step, index) => (
                <li data-event={text(step.event)} key={`${number(step.atMs)}-${index}`}>
                  <span />
                  <b>{browserActionLabel(text(step.action))}</b>
                  {text(step.target) ? <em>{text(step.target)}</em> : null}
                </li>
              ))}
            </ol>
            {steps.length > stepPreviewLimit ? (
              <button
                aria-label={showAllSteps ? `收起步骤到最近 ${stepPreviewLimit} 项` : `显示全部步骤：${steps.length} 项`}
                className="paw-browser-trace-steps-toggle"
                onClick={() => setShowAllSteps((value) => !value)}
                type="button"
              >
                {showAllSteps ? `收起到最近 ${stepPreviewLimit} 项` : `显示全部 ${steps.length} 项`}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function NativeBrowserWebview({
  active,
  onChange,
  onFoundInPage,
  onGuestState,
  onIdentity,
  onWebview,
  tab,
}: {
  active: boolean;
  onChange(value: { title: string; url: string; webContentsId: number }): void;
  onFoundInPage(match: BrowserFindMatch): void;
  onGuestState(update: Partial<HostBrowserTab>): void;
  onIdentity(webContentsId: number): void;
  onWebview(value: PawBrowserWebview | null): void;
  tab: HostBrowserTab;
}) {
  const ref = useRef<PawBrowserWebview | null>(null);
  const captureWebview = useCallback((webview: PawBrowserWebview | null) => {
    ref.current = webview;
    webview?.setAttribute('allowpopups', 'true');
  }, []);

  useEffect(() => {
    const webview = ref.current;
    if (!webview) return;
    onWebview(webview);
    const publish = () => {
      onChange({
        title: webview.getTitle() || (webview.getURL() === 'about:blank' ? '新标签页' : tab.title),
        url: webview.getURL() || tab.url,
        webContentsId: webview.getWebContentsId(),
      });
      onGuestState(guestNavigationState(webview));
    };
    const ready = () => {
      onIdentity(webview.getWebContentsId());
      publish();
    };
    const startLoading = () => onGuestState({ crashedReason: undefined, failure: null, loading: true });
    const stopLoading = () => onGuestState({ loading: false, ...guestNavigationState(webview) });
    const failLoad = (event: Event) => {
      const failure = event as PawBrowserGuestFailLoadEvent;
      // -3 is ERR_ABORTED: the person or a newer navigation cancelled the load.
      if (!failure.isMainFrame || failure.errorCode === -3) return;
      onGuestState({
        failure: {
          code: failure.errorCode,
          description: failure.errorDescription ?? '',
          url: failure.validatedURL ?? '',
        },
        loading: false,
      });
    };
    const processGone = (event: Event) => onGuestState({
      crashedReason: (event as PawBrowserGuestProcessGoneEvent).reason || 'crashed',
      loading: false,
    });
    const faviconUpdated = (event: Event) => {
      const favicon = (event as PawBrowserGuestFaviconEvent).favicons?.[0];
      if (favicon) onGuestState({ favicon });
    };
    const foundInPage = (event: Event) => {
      const result = (event as PawBrowserGuestFoundInPageEvent).result;
      if (!result) return;
      onFoundInPage({
        activeMatchOrdinal: typeof result.activeMatchOrdinal === 'number' ? result.activeMatchOrdinal : 0,
        matches: typeof result.matches === 'number' ? result.matches : 0,
      });
    };
    webview.addEventListener('dom-ready', ready);
    webview.addEventListener('did-navigate', publish);
    webview.addEventListener('did-navigate-in-page', publish);
    webview.addEventListener('page-title-updated', publish);
    webview.addEventListener('did-start-loading', startLoading);
    webview.addEventListener('did-stop-loading', stopLoading);
    webview.addEventListener('did-fail-load', failLoad);
    webview.addEventListener('render-process-gone', processGone);
    webview.addEventListener('page-favicon-updated', faviconUpdated);
    webview.addEventListener('found-in-page', foundInPage);
    return () => {
      webview.removeEventListener('dom-ready', ready);
      webview.removeEventListener('did-navigate', publish);
      webview.removeEventListener('did-navigate-in-page', publish);
      webview.removeEventListener('page-title-updated', publish);
      webview.removeEventListener('did-start-loading', startLoading);
      webview.removeEventListener('did-stop-loading', stopLoading);
      webview.removeEventListener('did-fail-load', failLoad);
      webview.removeEventListener('render-process-gone', processGone);
      webview.removeEventListener('page-favicon-updated', faviconUpdated);
      webview.removeEventListener('found-in-page', foundInPage);
      onWebview(null);
    };
  }, [onChange, onFoundInPage, onGuestState, onIdentity, onWebview, tab.title, tab.url]);

  return (
    <webview
      aria-label={tab.title || '网页内容'}
      className="paw-browser-native-webview"
      data-active={active || undefined}
      partition={PAW_BROWSER_PARTITION}
      ref={captureWebview}
      src={tab.url}
    />
  );
}
