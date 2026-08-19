const connection = document.querySelector('#connection');
const settingsForm = document.querySelector('#settings');
const bridgeUrl = document.querySelector('#bridge-url');
const pairingToken = document.querySelector('#pairing-token');
const displayName = document.querySelector('#display-name');
const autoSiteTransitions = document.querySelector('#auto-site-transitions');
const mode = document.querySelector('#mode');
const device = document.querySelector('#device');
const siteTransitions = document.querySelector('#site-transitions');
const lastSync = document.querySelector('#last-sync');
const pageTitle = document.querySelector('#page-title');
const pageUrl = document.querySelector('#page-url');

const modeLabels = { observe: '只读观察', codrive: '协同操作', managed: '托管执行' };

async function request(message) {
  const response = await chrome.runtime.sendMessage(message);
  if (!response?.ok) throw new Error(response?.error || '操作未完成');
  return response;
}

function setConnected(value, label = value ? '已连接' : '未连接') {
  connection.dataset.connected = String(Boolean(value));
  connection.textContent = label;
}

async function refresh() {
  try {
    const response = await request({ type: 'browser.panelStatus' });
    bridgeUrl.value = response.config.bridgeUrl || 'http://127.0.0.1:8766';
    pairingToken.value = response.config.pairingToken || '';
    displayName.value = response.config.displayName || '我的 Chrome';
    autoSiteTransitions.checked = response.config.autoApproveSiteTransitions !== false;
    mode.textContent = modeLabels[response.status.mode] || response.status.mode || '观察';
    device.textContent = response.config.displayName || response.config.deviceId;
    siteTransitions.textContent = autoSiteTransitions.checked ? '自动允许' : '逐次确认';
    setConnected(true);
    const snapshot = response.status.latestSnapshot;
    if (snapshot) {
      pageTitle.textContent = snapshot.title || '未命名页面';
      pageUrl.textContent = snapshot.url || '';
      lastSync.textContent = new Date(snapshot.createdAtMs).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
  } catch (error) {
    setConnected(false, '连接受限');
    pageUrl.textContent = String(error?.message || error);
  }
}

async function sync(includeScreenshot) {
  setConnected(false, '同步中');
  try {
    await request({ type: 'browser.pushSnapshot', includeScreenshot });
    await refresh();
  } catch (error) {
    setConnected(false, '同步失败');
    pageUrl.textContent = String(error?.message || error);
  }
}

document.querySelector('#toggle-settings').addEventListener('click', () => {
  settingsForm.hidden = !settingsForm.hidden;
});

settingsForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await request({
      type: 'browser.configure',
      settings: {
        bridgeUrl: bridgeUrl.value.trim(),
        pairingToken: pairingToken.value.trim(),
        displayName: displayName.value.trim(),
        autoApproveSiteTransitions: autoSiteTransitions.checked,
      },
    });
    settingsForm.hidden = true;
    await refresh();
  } catch (error) {
    setConnected(false, '连接失败');
    pageUrl.textContent = String(error?.message || error);
  }
});

document.querySelector('#sync').addEventListener('click', () => void sync(false));
document.querySelector('#capture').addEventListener('click', () => void sync(true));

void refresh();
setInterval(refresh, 5000);
