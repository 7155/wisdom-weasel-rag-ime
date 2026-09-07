import { execFileSync } from 'node:child_process';
// @ts-expect-error Existing jsdom dependency has no declarations.
import { JSDOM } from 'jsdom';
import { describe, expect, it, vi } from 'vitest';
const bridge = execFileSync('python3', ['-c', 'from rag_ime.agent_lab_app_runtime import browser_bridge; print(browser_bridge("standalone"))'], { cwd: '..', encoding: 'utf8' });
const model = { provider: 'openai-codex', model: 'gpt-5.6-luna', thinkingLevel: 'max' };

describe('portable App invocation transport', () => {
  it('keeps waiting through a long Pi turn and settles from the owner receipt', async () => {
    let elapsed = 0, reads = 0;
    const fetch = vi.fn(async (url: string) => {
      if (url.startsWith('/api/requests/')) reads += 1;
      return { ok: true, json: async () => ({ record: reads > 1
        ? { state: 'completed', result: { text: 'Owner answer' } }
        : { state: 'running', progress: { stage: 'thinking' } } }) };
    });
    const dom = new JSDOM(bridge, { runScripts: 'dangerously', url: 'http://localhost',
      beforeParse(window: Window & typeof globalThis) { Object.assign(window, { fetch }); window.Date.now = () => elapsed;
        window.setTimeout = ((callback: () => void) => { elapsed += 210000; queueMicrotask(callback); return 1; }) as typeof window.setTimeout; } });
    try {
      const result = await dom.window.pawApp.invoke('answer', { question: 'Original input' }, { model });
      expect(result.text).toBe('Owner answer'); expect(elapsed).toBeGreaterThan(195000);
      expect(fetch.mock.calls.filter(([url]) => url === '/api/invoke')).toHaveLength(1);
    } finally { dom.window.close(); }
  });
  it('reads a saved request after reload instead of resubmitting it to a newer App version', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ record: { state: 'completed', result: { text: 'Saved answer' } } }) }));
    const dom = new JSDOM(bridge, { runScripts: 'dangerously', url: 'http://localhost', beforeParse(window: Window & typeof globalThis) { Object.assign(window, { fetch }); } });
    try {
      const input = { question: 'Original input' };
      dom.window.sessionStorage.setItem('paw.app.pending.v1', JSON.stringify({ [JSON.stringify(['answer', input, model])]: '11111111-1111-4111-8111-111111111111' }));
      expect((await dom.window.pawApp.invoke('answer', input, { model })).text).toBe('Saved answer');
      expect(fetch).toHaveBeenCalledWith('/api/requests/11111111-1111-4111-8111-111111111111', { cache: 'no-store' });
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(dom.window.sessionStorage.getItem('paw.app.pending.v1')).toBe('{}');
    } finally { dom.window.close(); }
  });
});
