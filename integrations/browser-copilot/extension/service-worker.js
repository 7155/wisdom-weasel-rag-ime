const DEFAULT_BRIDGE_URL = 'http://127.0.0.1:8766';
let pollRunning = false;
const passivePushTimers = new Map();

async function settings() {
  const stored = await chrome.storage.local.get([
    'bridgeUrl',
    'pairingToken',
    'deviceId',
    'displayName',
    'clientKind',
    'managedBootstrapToken',
    'autoApproveSiteTransitions',
  ]);
  let pairingToken = String(stored.pairingToken || '');
  const bridgeUrl = String(stored.bridgeUrl || DEFAULT_BRIDGE_URL).replace(/\/+$/, '');
  let clientKind = String(stored.clientKind || 'user');
  let managedBootstrapToken = String(stored.managedBootstrapToken || '');
  const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  try {
    const activeUrl = new URL(String(active?.url || ''));
    if (
      activeUrl.hostname === '127.0.0.1'
      && activeUrl.pathname === '/api/browser/managed/bootstrap'
      && activeUrl.searchParams.get('token')
    ) {
      clientKind = 'managed';
      managedBootstrapToken = String(activeUrl.searchParams.get('token'));
    }
  } catch {
    // A browser-internal page cannot carry a managed bootstrap marker.
  }
  if (!pairingToken) {
    try {
      const response = await fetch(`${bridgeUrl}/api/browser/pairing`, { cache: 'no-store' });
      if (response.ok) {
        const pairing = await response.json();
        pairingToken = String(pairing.pairingToken || '');
      }
    } catch {
      // The panel will show the disconnected state until the local runtime starts.
    }
  }
  const deviceId = String(stored.deviceId || `chrome_${crypto.randomUUID().replaceAll('-', '')}`);
  const next = {
    bridgeUrl,
    pairingToken,
    deviceId,
    displayName: String(stored.displayName || (clientKind === 'managed' ? '托管 Chrome' : '我的 Chrome')),
    clientKind,
    managedBootstrapToken,
    autoApproveSiteTransitions: stored.autoApproveSiteTransitions !== false,
  };
  await chrome.storage.local.set(next);
  return next;
}

async function bridgeFetch(path, options = {}) {
  const config = await settings();
  if (!config.pairingToken) throw new Error('尚未取得浏览器配对凭据');
  const response = await fetch(`${config.bridgeUrl}${path}`, {
    ...options,
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      'X-RAG-IME-Browser-Token': config.pairingToken,
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `控制中心返回 ${response.status}`);
  return payload;
}

async function hello() {
  const config = await settings();
  const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const response = await bridgeFetch('/api/browser/extension/hello', {
    method: 'POST',
    body: JSON.stringify({
      deviceId: config.deviceId,
      displayName: config.displayName,
      clientKind: config.clientKind,
      extensionVersion: chrome.runtime.getManifest().version,
      browserName: navigator.userAgent.includes('Chrome') ? 'Chrome' : 'Chromium',
      activeTabId: active?.id,
      managedBootstrapToken: config.managedBootstrapToken,
    }),
  });
  if (config.clientKind === 'managed' && active?.id) {
    try {
      const activeUrl = new URL(String(active.url || ''));
      if (activeUrl.pathname === '/api/browser/managed/bootstrap') {
        await chrome.tabs.update(active.id, { url: 'about:blank' });
      }
    } catch {
      // The managed profile may already have moved to a regular page.
    }
  }
  return response;
}

function parseReference(refId) {
  const match = String(refId || '').match(/^(?:(\d+):)?(e\d+)$/);
  if (!match) return { frameId: 0, localRefId: String(refId || '') };
  return { frameId: Number(match[1] || 0), localRefId: match[2] };
}

async function sendFrameCommand(tabId, frameId, message) {
  return chrome.tabs.sendMessage(tabId, { type: 'browser.command', ...message }, { frameId });
}

async function collectSnapshot(tabId, includeScreenshot = false) {
  const tab = await chrome.tabs.get(tabId);
  const frames = await chrome.webNavigation.getAllFrames({ tabId }).catch(() => []);
  const frameIds = frames.length ? frames.map((frame) => frame.frameId) : [0];
  const snapshots = [];
  for (const frameId of frameIds.slice(0, 24)) {
    try {
      const snapshot = await sendFrameCommand(tabId, frameId, { action: 'snapshot' });
      if (snapshot?.ok) snapshots.push({ frameId, ...snapshot });
    } catch {
      // Chrome internal pages and cross-origin frames may not host the content script.
    }
  }
  const main = snapshots.find((snapshot) => snapshot.frameId === 0) || snapshots[0];
  if (!main) throw new Error('当前标签页不允许读取，请切换到普通 http/https 页面');
  const markdown = snapshots
    .map((snapshot) => {
      const scoped = String(snapshot.markdown || '').replace(/\[e(\d+)\]/g, `[${snapshot.frameId}:e$1]`);
      return `## Frame ${snapshot.frameId}\n${scoped}`;
    })
    .join('\n\n')
    .slice(0, 160000);
  const result = {
    snapshotId: main.snapshotId,
    tabId,
    frameId: 0,
    url: tab.url || main.url || '',
    title: tab.title || main.title || '',
    summary: `${snapshots.length} 个 Frame · ${snapshots.reduce((sum, item) => sum + Number(item.interactiveCount || 0), 0)} 个可交互元素`,
    markdown,
    interactiveCount: snapshots.reduce((sum, item) => sum + Number(item.interactiveCount || 0), 0),
    viewport: main.viewport || {},
  };
  if (includeScreenshot) {
    result.screenshotDataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  }
  return result;
}

async function pushSnapshot(tabId, includeScreenshot = false) {
  const config = await settings();
  const snapshot = await collectSnapshot(tabId, includeScreenshot);
  return bridgeFetch('/api/browser/extension/snapshot', {
    method: 'POST',
    body: JSON.stringify({ deviceId: config.deviceId, ...snapshot }),
  });
}

async function requireCrossOriginPermission(tab, targetUrl) {
  const current = new URL(String(tab.url || 'about:blank'));
  const target = new URL(String(targetUrl || ''));
  if (current.origin === target.origin) return;
  const config = await settings();
  const response = await bridgeFetch('/api/browser/extension/permission', {
    method: 'POST',
    body: JSON.stringify({
      deviceId: config.deviceId,
      origin: target.href,
      action: 'domain_transition',
      reason: `从 ${current.hostname || current.protocol} 前往 ${target.hostname}`,
      autoApprove: config.autoApproveSiteTransitions,
    }),
  });
  if (response.authorized === true) return;
  throw new Error(`已请求访问 ${target.hostname} 的站点权限，请在控制中心批准后重试`);
}

async function execute(command) {
  const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const tabId = Number(command.tabId || active?.id || 0);
  if (!tabId) throw new Error('没有可操作的活动标签页');
  if (command.action === 'tabs') {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    return {
      ok: true,
      summary: `当前窗口有 ${tabs.length} 个标签页`,
      tabs: tabs.map((tab) => ({ tabId: tab.id, title: tab.title, url: tab.url, active: tab.active })),
    };
  }
  if (command.action === 'snapshot' || command.action === 'read_page') {
    return { ok: true, ...(await collectSnapshot(tabId, false)) };
  }
  if (command.action === 'screenshot') {
    return { ok: true, summary: '已截取当前可视页面', ...(await collectSnapshot(tabId, true)) };
  }
  if (command.action === 'navigate') {
    const tab = await chrome.tabs.get(tabId);
    await requireCrossOriginPermission(tab, command.url);
    await chrome.tabs.update(tabId, { url: String(command.url || '') });
    await waitForTab(tabId, 20000);
    return { ok: true, summary: `已打开 ${command.url}`, ...(await collectSnapshot(tabId, false)) };
  }
  const { frameId, localRefId } = parseReference(command.refId);
  return sendFrameCommand(tabId, frameId, { ...command, refId: localRefId });
}

async function waitForTab(tabId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === 'complete') return;
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error('页面导航超时');
}

async function complete(commandId, result) {
  return bridgeFetch('/api/browser/extension/result', {
    method: 'POST',
    body: JSON.stringify({ commandId, result }),
  });
}

async function poll() {
  if (pollRunning) return;
  pollRunning = true;
  while (pollRunning) {
    try {
      const config = await settings();
      if (!config.pairingToken) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        continue;
      }
      await hello();
      const params = new URLSearchParams({
        deviceId: config.deviceId,
        clientId: `${config.deviceId}:worker`,
        timeoutSeconds: '20',
      });
      const response = await bridgeFetch(`/api/browser/extension/next?${params}`);
      if (!response.command) continue;
      const startedAt = performance.now();
      try {
        const result = await execute(response.command);
        await complete(response.command.commandId, {
          ...result,
          durationMs: Math.round(performance.now() - startedAt),
        });
      } catch (error) {
        await complete(response.command.commandId, {
          ok: false,
          error: String(error?.message || error),
          failureReason: 'extension_command_failed',
          durationMs: Math.round(performance.now() - startedAt),
        });
      }
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
  }
}

function schedulePassivePush(tabId) {
  clearTimeout(passivePushTimers.get(tabId));
  passivePushTimers.set(tabId, setTimeout(() => {
    passivePushTimers.delete(tabId);
    pushSnapshot(tabId).catch(() => undefined);
  }, 500));
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => undefined);
  void poll();
});

chrome.runtime.onStartup.addListener(() => void poll());
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'browser.pageChanged' && sender.tab?.id) {
    schedulePassivePush(sender.tab.id);
    return undefined;
  }
  if (message?.type === 'browser.configure') {
    chrome.storage.local
      .set(message.settings || {})
      .then(async () => {
        await hello();
        void poll();
        sendResponse({ ok: true });
      })
      .catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }
  if (message?.type === 'browser.panelStatus') {
    Promise.all([settings(), hello(), bridgeFetch('/api/browser/status')])
      .then(([config, _helloStatus, status]) => sendResponse({ ok: true, config, status }))
      .catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }
  if (message?.type === 'browser.pushSnapshot') {
    chrome.tabs.query({ active: true, lastFocusedWindow: true })
      .then(([tab]) => {
        if (!tab?.id) throw new Error('没有活动标签页');
        return pushSnapshot(tab.id, message.includeScreenshot === true);
      })
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }
  return undefined;
});

chrome.tabs.onActivated.addListener(({ tabId }) => schedulePassivePush(tabId));
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === 'complete') schedulePassivePush(tabId);
});

void poll();
