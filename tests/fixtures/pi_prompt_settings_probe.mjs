import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const sdk = process.argv[2];
const { compactionInstructions } = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const serializedInstructions = JSON.stringify(compactionInstructions).slice(1, -1);
const { AgentSession } = await import(pathToFileURL(path.join(sdk, 'dist/core/agent-session.js')).href);
const { SettingsManager } = await import(pathToFileURL(path.join(sdk, 'dist/core/settings-manager.js')).href);
const session = Object.create(AgentSession.prototype);
session.settingsManager = SettingsManager.inMemory({ compaction: { reserveTokens: 1024, keepRecentTokens: 128 } });
session.settingsManager.applyOverrides({ compaction: { instructions: compactionInstructions } });
assert.equal(session.settingsManager.getCompactionSettings().reserveTokens, 1024);
const model = { id: 'offline', name: 'Offline probe', provider: 'offline', api: 'openai-completions',
  contextWindow: 32000, maxTokens: 4096, reasoning: false, input: ['text'],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
const controller = new AbortController();
const calls = [];
session.agent = { state: { thinkingLevel: 'off' }, streamFunction: async (_model, context, options) => {
  assert.equal(options.signal, controller.signal);
  calls.push(JSON.stringify(context));
  return { result: async () => ({ role: 'assistant', content: [{ type: 'text', text: 'Offline summary receipt' }],
    api: model.api, provider: model.provider, model: model.id, stopReason: 'stop', timestamp: 1,
    usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } }) };
} };
session._summarizationRetryCallbacks = () => undefined;
const message = { role: 'user', content: [{ type: 'text', text: 'Continue the confirmed change; verify the pending check.' }], timestamp: 1 };
const preparation = { firstKeptEntryId: 'kept-entry', messagesToSummarize: [message],
  turnPrefixMessages: [], isSplitTurn: false, tokensBefore: 4000,
  fileOps: { read: new Set(['PROJECT.md']), edited: new Set(['OUTCOMES.md']), written: new Set() },
  settings: session.settingsManager.getCompactionSettings() };
const cases = [];
for (const split of [false, true]) {
  for (const manual of [false, true]) {
    const start = calls.length;
    const result = await session._runDefaultCompaction(
      { ...preparation, isSplitTurn: split, turnPrefixMessages: split ? [message] : [] },
      model, 'offline-key', undefined, manual ? 'MANUAL_FOCUS' : undefined,
      controller.signal, {}, manual ? 'manual' : 'threshold',
    );
    const emitted = calls.slice(start);
    assert.equal(emitted.length, split ? 2 : 1);
    for (const prompt of emitted) {
      assert.ok(prompt.includes(serializedInstructions));
      assert.ok(prompt.includes('Next Steps'), 'summary request must ask for a docs recovery step');
      assert.ok(prompt.includes('接续 Agent'), 'recovery instruction must address the continuing agent');
      assert.ok(prompt.includes('用途'), 'document references must explain what to recover');
      assert.ok(prompt.includes('不要求重读全部 docs'), 'recovery must avoid blanket rereading');
      assert.ok(prompt.includes('不调用工具'), 'summarization must remain summary-only');
      assert.equal(prompt.includes('MANUAL_FOCUS'), manual);
    }
    assert.ok(result.summary.includes('<read-files>\nPROJECT.md'));
    assert.ok(result.summary.includes('<modified-files>\nOUTCOMES.md'));
    cases.push({ mode: manual ? 'manual' : 'automatic', splitTurn: split, summaryRequests: emitted.length, passed: true });
  }
}
session.settingsManager.applyOverrides({ compaction: { instructions: '' } });
const start = calls.length;
await session._runDefaultCompaction(preparation, model, 'offline-key', undefined, 'MANUAL_ONLY', controller.signal, {}, 'manual');
assert.equal(calls.length - start, 1);
assert.ok(!calls.at(-1).includes(serializedInstructions));
assert.ok(calls.at(-1).includes('MANUAL_ONLY'));
cases.push({ mode: 'manual-empty-default', summaryRequests: 1, passed: true });
process.stdout.write(`${JSON.stringify({ ok: true, actualSdk: true, modelCalls: 'offline stub', cases }, null, 2)}\n`);
