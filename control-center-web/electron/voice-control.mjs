import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFile } from 'node:child_process';

const providers = new Set(['native_streaming', 'realtime_websocket', 'http_transcription']);
const notifications = new Set(['reload_configuration', 'request_microphone_permission', 'request_accessibility_permission']);

export function trustedVoiceSender(event, window, origin) {
  return Boolean(window && event.sender === window.webContents
    && event.senderFrame === window.webContents.mainFrame
    && new URL(event.senderFrame.url).origin === origin);
}

function run(file, args, input) {
  return new Promise((resolve, reject) => {
    const child = execFile(file, args, { timeout: 15_000, maxBuffer: 65_536 }, (error, stdout) => {
      if (error) reject(new Error('本机语音操作失败，请检查语音服务安装和系统授权。'));
      else resolve(stdout);
    });
    child.stdin.on('error', () => {});
    child.stdin.end(input === undefined ? undefined : JSON.stringify(input));
  });
}

export function createVoiceControl({ home = os.homedir(), execute = run, readFile = fs.readFileSync, alive = (pid) => { try { process.kill(pid, 0); return true; } catch { return false; } } } = {}) {
  const helper = path.join(home, 'Applications/RagImeVoice.app/Contents/MacOS/RagImeVoice');
  const statusPath = path.join(home, 'Library/Application Support/RagIme/voice-agent-status.json');
  const label = `gui/${process.getuid()}/com.rag-ime.voice`;
  const status = () => {
    let data = {};
    try { data = JSON.parse(readFile(statusPath, 'utf8')); } catch { /* Not yet started. */ }
    const running = data.running === true && Number.isInteger(data.processID) && data.processID > 0 && alive(data.processID);
    return { running, state: running ? String(data.state || 'idle') : 'stopped',
      statusText: running ? String(data.statusText || '语音服务运行中') : '语音服务未运行',
      microphoneAuthorization: String(data.microphoneAuthorization || 'notDetermined'),
      accessibilityTrusted: data.accessibilityTrusted === true,
      hotkeyInstalled: running && data.hotkeyInstalled === true,
      hotkeyMode: String(data.hotkeyMode || ''), updatedAtMs: Number(data.updatedAtMs) || 0 };
  };
  const call = async (request) => JSON.parse(await execute(helper, ['--desktop-control'], request));
  return {
    status,
    async credentialStatus(provider) {
      if (!providers.has(provider)) throw new Error('未知转写引擎');
      return call({ operation: 'credential_status', provider });
    },
    async saveCredentials(request) {
      const allowed = new Set(['provider', 'appId', 'accessToken', 'resourceId', 'endpoint', 'model', 'headersJson']);
      if (!request || !providers.has(request.provider) || Object.entries(request).some(([key, value]) => !allowed.has(key) || typeof value !== 'string') || JSON.stringify(request).length > 32_768) throw new Error('语音连接参数无效');
      return call({ ...request, operation: 'save_credentials' });
    },
    async action(action) {
      if (action === 'start_agent') {
        await execute('/bin/launchctl', ['enable', label]);
        try { await execute('/bin/launchctl', ['print', label]); }
        catch { await execute('/bin/launchctl', ['bootstrap', `gui/${process.getuid()}`, path.join(home, 'Library/LaunchAgents/com.rag-ime.voice.plist')]); }
        await execute('/bin/launchctl', ['kickstart', label]);
      } else if (action === 'stop_agent') {
        await execute('/bin/launchctl', ['bootout', label]);
      } else if (notifications.has(action)) {
        if (!status().running) throw new Error('请先启动语音服务');
        await call({ operation: action });
      } else if (action === 'open_microphone_settings' || action === 'open_accessibility_settings') {
        await execute('/usr/bin/open', [`x-apple.systempreferences:com.apple.preference.security?Privacy_${action === 'open_microphone_settings' ? 'Microphone' : 'Accessibility'}`]);
      } else throw new Error('未知语音操作');
      return { action, accepted: true, status: status() };
    },
  };
}
