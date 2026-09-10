import assert from 'node:assert/strict';
import test from 'node:test';
import { createVoiceControl, trustedVoiceSender } from './voice-control.mjs';

test('only the main trusted application frame can control voice', () => {
  const mainFrame = { url: 'http://127.0.0.1:8770/?pawHost=electron' };
  const webContents = { mainFrame };
  assert.equal(trustedVoiceSender({ sender: webContents, senderFrame: mainFrame }, { webContents }, 'http://127.0.0.1:8770'), true);
  assert.equal(trustedVoiceSender({ sender: webContents, senderFrame: { ...mainFrame } }, { webContents }, 'http://127.0.0.1:8770'), false);
  mainFrame.url = 'https://example.com';
  assert.equal(trustedVoiceSender({ sender: webContents, senderFrame: mainFrame }, { webContents }, 'http://127.0.0.1:8770'), false);
});

test('dead process cannot be reported as running by an old status file', () => {
  const voice = createVoiceControl({ readFile: () => '{"running":true,"processID":123}', alive: () => false });
  assert.equal(voice.status().running, false);
});

test('permission actions notify the existing voice owner; invalid commands never execute', async () => {
  const calls = [];
  const voice = createVoiceControl({ home: '/Users/test', readFile: () => '{"running":true,"processID":123}', alive: () => true,
    execute: async (...args) => { calls.push(args); return '{"accepted":true}'; } });
  await voice.action('request_microphone_permission');
  assert.deepEqual(calls[0], ['/Users/test/Applications/RagImeVoice.app/Contents/MacOS/RagImeVoice', ['--desktop-control'], { operation: 'request_microphone_permission' }]);
  await assert.rejects(voice.action('arbitrary_command'));
  assert.equal(calls.length, 1);
});

test('credentials use stdin; provider and field allowlists reject invalid writes', async () => {
  const calls = [];
  const voice = createVoiceControl({ execute: async (...args) => { calls.push(args); return '{"configured":true,"provider":"native_streaming"}'; } });
  await voice.saveCredentials({ provider: 'native_streaming', accessToken: 'test-token' });
  assert.deepEqual(calls[0][1], ['--desktop-control']);
  assert.equal(calls[0][2].accessToken, 'test-token');
  await assert.rejects(voice.saveCredentials({ provider: 'native_streaming', command: 'invalid' }));
  await assert.rejects(voice.credentialStatus('invalid'));
  assert.equal(calls.length, 1);
});
