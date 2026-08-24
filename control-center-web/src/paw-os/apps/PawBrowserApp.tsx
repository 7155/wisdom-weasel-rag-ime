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
  LockKeyhole,
  PanelRightClose,
  PanelRightOpen,
  Plus,
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
import { useCallback, useEffect, useRef, useState, type FormEvent, type WheelEvent } from 'react';
import { useControlTransport } from '@/app/control-transport';
import {
  PAW_BROWSER_PARTITION,
  loadPawBrowserUrl,
  pawBrowserHost,
  type PawBrowserHistoryEntry,
  type PawBrowserWebview,
  type PawBrowserSettings,
} from './paw-browser-host';
import { PawWindowChromePortal, usePawWindowChromeTarget } from '../shell/PawWindowChrome';
import type { PawOsWindowTarget } from '@/features/paw-os/model/desktop';

type BrowserRecord = Record<string, unknown>;

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
  const [zoomPercent, setZoomPercent] = useState(100);
  const [browserActionReceipt, setBrowserActionReceipt] = useState('');
  const hostWebviews = useRef(new Map<string, PawBrowserWebview>());
  const started = useRef(false);
  const openedTargetCommand = useRef('');
  const appliedTargetSelection = useRef('');
  const selectedTab = tabs.find((tab) => number(tab.tabId) === selectedTabId) ?? tabs[0];
  const selectedHostTab = hostTabs.find((tab) => tab.id === selectedHostTabId) ?? hostTabs[0];
  const selectedTabUrl = electronHost ? selectedHostTab?.url ?? 'about:blank' : text(selectedTab?.url);
  const displayedTabs = electronHost
    ? hostTabs.map((tab, index) => ({ ...tab, tabId: index + 1 }))
    : tabs;
  const displayedSelectedTabId = electronHost
    ? Math.max(1, hostTabs.findIndex((tab) => tab.id === selectedHostTabId) + 1)
    : selectedTabId;

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

  const submitAddress = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    navigateTo(address);
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
    const label = action === 'cache' ? '缓存' : 'Cookie 与站点数据';
    if (!electronHost || !window.confirm(`确认清除当前 PAW Browser Profile 的${label}？`)) return;
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
      return;
    }
    selectedWebview()?.findInPage(value, { findNext, forward });
  };

  const closeFind = () => {
    selectedWebview()?.stopFindInPage('clearSelection');
    setFindDraft('');
    setShowFind(false);
  };

  const changeZoom = (step: number) => {
    const webview = selectedWebview();
    if (!webview) return;
    const next = Math.min(300, Math.max(25, zoomPercent + step));
    webview.setZoomFactor(next / 100);
    setZoomPercent(next);
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
    if (!electronHost || !window.confirm('确认清空当前 PAW Browser Profile 的全部浏览历史？')) return;
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

  const visibleHistory = history.filter((entry) => {
    const query = historyQuery.trim().toLocaleLowerCase();
    return !query || entry.title.toLocaleLowerCase().includes(query) || entry.url.toLocaleLowerCase().includes(query);
  });

  const browserTabs = (
    <div className="paw-browser-tabstrip" data-window-chrome={windowChromeTarget ? true : undefined}>
      <div className="paw-browser-tabs-live" role="tablist" aria-label="PAW Browser 标签页">
        {displayedTabs.map((tab) => {
          const tabId = number(tab.tabId);
          const hostTabId = text(tab.id);
          const isTabActive = tabId === displayedSelectedTabId;
          return (
            <div className="paw-browser-tab" data-active={isTabActive || undefined} key={hostTabId || tabId} role="presentation">
              <button
                aria-selected={isTabActive}
                className="paw-browser-tab-main"
                onClick={() => electronHost && hostTabId ? setSelectedHostTabId(hostTabId) : setSelectedTabId(tabId)}
                role="tab"
                type="button"
              >
                <Globe2 size={13} />
                <span>{text(tab.title) || '新标签页'}</span>
              </button>
              {isTabActive ? (
                <button
                  aria-label="关闭标签页"
                  className="paw-browser-tab-close"
                  onClick={() => {
                    if (electronHost && hostTabId) closeHostTab(hostTabId);
                    else void run('close_tab');
                  }}
                  type="button"
                >
                  <X size={12} />
                </button>
              ) : null}
            </div>
          );
        })}
        <button
          aria-label="新建标签页"
          className="paw-browser-new-tab"
          disabled={Boolean(busy)}
          onClick={() => electronHost ? addHostTab() : void run('new_tab', { url: 'about:blank' })}
          type="button"
        >
          <Plus size={14} />
        </button>
      </div>
    </div>
  );

  return (
    <>
      {windowChromeTarget ? <PawWindowChromePortal>{browserTabs}</PawWindowChromePortal> : null}
      <main className="paw-direct-browser" data-tabs-in-window-chrome={windowChromeTarget ? true : undefined}>
        {windowChromeTarget ? null : browserTabs}

      <section className="paw-browser-toolbar">
        <div className="paw-nav-buttons">
          <button aria-label="后退" disabled={electronHost ? !selectedHostTab : !selectedTabId || Boolean(busy)} onClick={() => runNavigation('back')} type="button">
            <ArrowLeft size={15} />
          </button>
          <button aria-label="前进" disabled={electronHost ? !selectedHostTab : !selectedTabId || Boolean(busy)} onClick={() => runNavigation('forward')} type="button">
            <ArrowRight size={15} />
          </button>
          <button
            aria-label="刷新网页"
            disabled={electronHost ? !selectedHostTab : !selectedTabId || Boolean(busy)}
            onClick={() => runNavigation('reload')}
            type="button"
          >
            <RefreshCw className={busy === 'reload' ? 'ui-spin' : ''} size={14} />
          </button>
          <button aria-label="空白页" className="paw-browser-home" onClick={() => navigateTo('about:blank')} type="button">
            <Home size={14} />
          </button>
        </div>

        <form className="paw-omnibox-form" onSubmit={submitAddress}>
          <LockKeyhole className="paw-lock-icon" size={13} />
          <input
            aria-label="页面地址"
            onChange={(event) => setAddress(event.target.value)}
            placeholder="输入网址或搜索内容…"
            spellCheck={false}
            value={address}
          />
          {address ? (
            <button className="paw-omnibox-clear" onClick={() => setAddress('')} type="button">
              <X size={12} />
            </button>
          ) : null}
        </form>

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
            title="Browser 设置"
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
            type="button"
          >
            <EllipsisVertical size={14} />
          </button>
          {electronHost && showBrowserMenu ? (
            <div className="paw-browser-menu" role="menu">
              <button onClick={() => { setShowFind(true); setShowBrowserMenu(false); }} role="menuitem" type="button"><Search size={13} />页内查找</button>
              <button onClick={() => { selectedWebview()?.print(); setShowBrowserMenu(false); }} role="menuitem" type="button"><Printer size={13} />打印</button>
              <div className="paw-browser-menu-zoom"><span>缩放</span><button aria-label="缩小网页" onClick={() => changeZoom(-10)} type="button"><ZoomOut size={13} /></button><b>{zoomPercent}%</b><button aria-label="放大网页" onClick={() => changeZoom(10)} type="button"><ZoomIn size={13} /></button></div>
              <button onClick={() => void takeScreenshot()} role="menuitem" type="button"><Camera size={13} />截图</button>
              <button onClick={() => void openDownloads()} role="menuitem" type="button"><Download size={13} />下载</button>
              <button className="paw-browser-menu-narrow-only" onClick={() => { setShowSettings(false); setShowHistory(true); setShowBrowserMenu(false); void refreshBrowserHistory(); }} role="menuitem" type="button"><History size={13} />浏览历史</button>
              <button onClick={() => { setShowHistory(false); setShowSettings(true); setShowBrowserMenu(false); void refreshBrowserSettings(); }} role="menuitem" type="button"><CircleX size={13} />清除浏览数据</button>
              <button className="paw-browser-menu-narrow-only" onClick={() => { setShowHistory(false); setShowSettings(true); setShowBrowserMenu(false); void refreshBrowserSettings(); }} role="menuitem" type="button"><Settings size={13} />浏览器设置</button>
            </div>
          ) : null}
        </div>
      </section>

      <section className="paw-browser-workspace" data-show-agent={showTrace || undefined}>
        <div className="paw-browser-viewport" data-agent-state={agentExecutionState || undefined}>
          {electronHost && showFind ? (
            <div className="paw-browser-find" role="search"><input aria-label="页内查找" autoFocus onChange={(event) => findOnPage(event.target.value)} value={findDraft} /><button aria-label="上一个匹配项" onClick={() => findOnPage(findDraft, true, false)} type="button"><ArrowLeft size={13} /></button><button aria-label="下一个匹配项" onClick={() => findOnPage(findDraft, true, true)} type="button"><ArrowRight size={13} /></button><button aria-label="关闭页内查找" onClick={closeFind} type="button"><X size={13} /></button></div>
          ) : null}
          {browserActionReceipt ? <output className="paw-browser-action-receipt" role="status">{browserActionReceipt}</output> : null}
          {showHistory ? (
            <section aria-label="浏览历史" className="paw-browser-history">
              <div className="paw-browser-surface-card">
                <header>
                  <div><History size={16} /><strong>浏览历史</strong></div>
                  <div>
                    <button disabled={!history.length || Boolean(busy)} onClick={() => void clearHistory()} type="button">清空</button>
                    <button aria-label="关闭浏览历史" onClick={() => setShowHistory(false)} type="button"><X size={14} /></button>
                  </div>
                </header>
                <label className="paw-browser-history-search"><Search size={13} /><input aria-label="搜索浏览历史" onChange={(event) => setHistoryQuery(event.target.value)} placeholder="搜索标题或网址" type="search" value={historyQuery} /></label>
                {visibleHistory.length ? (
                  <ol>
                    {visibleHistory.map((entry) => (
                      <li key={`${entry.visitedAt}-${entry.url}`}>
                        <button onClick={() => { setShowHistory(false); navigateTo(entry.url); }} type="button">
                          <Globe2 size={14} />
                          <span><strong>{entry.title || entry.url}</strong><small>{entry.url}</small></span>
                          <time>{historyTime(entry.visitedAt)}</time>
                        </button>
                        <button aria-label={`删除 ${entry.title || entry.url}`} onClick={() => void removeHistoryEntry(entry.id)} type="button"><X size={13} /></button>
                      </li>
                    ))}
                  </ol>
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
                  <section><h3>浏览数据</h3><div className="paw-browser-setting-row"><span>缓存 · {formatBytes(browserSettings?.cacheBytes ?? 0)}</span><button disabled={Boolean(busy)} onClick={() => void clearBrowserData('cache')} type="button">清除缓存</button></div><div className="paw-browser-setting-row"><span>Cookie 与站点数据 · {browserSettings?.cookieCount ?? 0} 个 Cookie</span><button disabled={Boolean(busy)} onClick={() => void clearBrowserData('site-data')} type="button">清除 Cookie 与站点数据</button></div></section>
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

function normalizedAddress(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed === 'about:blank') return trimmed;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^[\w.-]+\.[a-z]{2,}(?:\/.*)?$/i.test(trimmed)) return `https://${trimmed}`;
  return `https://www.google.com/search?q=${encodeURIComponent(trimmed)}`;
}

function record(value: unknown): BrowserRecord { return value && typeof value === 'object' && !Array.isArray(value) ? value as BrowserRecord : {}; }
function rows(value: unknown): BrowserRecord[] { return Array.isArray(value) ? value.map(record) : []; }
function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
function number(value: unknown): number { return typeof value === 'number' && Number.isFinite(value) ? value : 0; }
function errorText(value: unknown): string { return value instanceof Error && value.message ? value.message : '本机浏览器服务没有返回结果。'; }

type BrowserElement = {
  refId: string;
  tag: string;
  role: string;
  label: string;
  inputType: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

function browserElement(value: BrowserRecord): BrowserElement | null {
  const refId = text(value.refId);
  const width = number(value.width);
  const height = number(value.height);
  if (!refId || width <= 0 || height <= 0) return null;
  return {
    refId,
    tag: text(value.tag),
    role: text(value.role),
    label: text(value.label),
    inputType: text(value.inputType),
    x: number(value.x),
    y: number(value.y),
    width,
    height,
  };
}

function isTextEntry(element: BrowserElement): boolean {
  return element.tag === 'input'
    || element.tag === 'textarea'
    || element.tag === 'select'
    || element.role === 'textbox'
    || element.role === 'searchbox';
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

type HostBrowserTab = {
  commandId?: string;
  id: string;
  title: string;
  url: string;
  webContentsId?: number;
};

function historyTime(value: number): string {
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(value);
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function initialHostTab(): HostBrowserTab {
  return { id: 'paw-tab-1', title: '新标签页', url: 'about:blank' };
}

function hostTab(url: string, commandId?: string): HostBrowserTab {
  const id = typeof crypto.randomUUID === 'function'
    ? `paw-tab-${crypto.randomUUID()}`
    : `paw-tab-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return { commandId, id, title: url === 'about:blank' ? '新标签页' : url, url };
}

function knownCount(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return Math.floor(value);
  }
  return null;
}

function NativeBrowserWebview({
  active,
  onChange,
  onIdentity,
  onWebview,
  tab,
}: {
  active: boolean;
  onChange(value: { title: string; url: string; webContentsId: number }): void;
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
    const publish = () => onChange({
      title: webview.getTitle() || (webview.getURL() === 'about:blank' ? '新标签页' : tab.title),
      url: webview.getURL() || tab.url,
      webContentsId: webview.getWebContentsId(),
    });
    const ready = () => {
      onIdentity(webview.getWebContentsId());
      publish();
    };
    webview.addEventListener('dom-ready', ready);
    webview.addEventListener('did-navigate', publish);
    webview.addEventListener('did-navigate-in-page', publish);
    webview.addEventListener('page-title-updated', publish);
    return () => {
      webview.removeEventListener('dom-ready', ready);
      webview.removeEventListener('did-navigate', publish);
      webview.removeEventListener('did-navigate-in-page', publish);
      webview.removeEventListener('page-title-updated', publish);
      onWebview(null);
    };
  }, [onChange, onIdentity, onWebview, tab.title, tab.url]);

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

function browserActionLabel(action: string): string {
  return ({
    run: '执行网页任务',
    navigate: '打开页面',
    new_tab: '新建标签页',
    close_tab: '关闭标签页',
    reload: '刷新页面',
    back: '后退',
    forward: '前进',
    click: '点击',
    type: '输入',
    scroll: '滚动',
    wait: '等待页面',
    snapshot: '读取页面',
    screenshot: '截取页面',
    read_page: '读取页面',
    hover: '指向',
    drag: '拖动',
    press: '按键',
    select: '选择',
    check: '勾选',
    uncheck: '取消勾选',
    upload: '上传文件',
    switch_tab: '切换标签页',
    task_space: '进入任务空间',
    task_complete: '完成任务空间',
    hand_off: '交给你操作',
    take_over: '接管页面',
    wait_for_control: '等待接管',
  } as Record<string, string>)[action] ?? action;
}
