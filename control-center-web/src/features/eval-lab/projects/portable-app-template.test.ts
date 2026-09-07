import { readFileSync } from 'node:fs';
// @ts-expect-error The existing jsdom test dependency has no bundled declarations.
import { JSDOM } from 'jsdom';
import { describe, expect, it, vi } from 'vitest';
const template = readFileSync('../integrations/pi/skills/agent-lab-project/assets/portable-app.html', 'utf8');
const sources = [{ sourceId: 'manual', title: 'Real manual', uri: 'https://example.test/manual', text: 'Supported steps.' }];
const knowledge = { retrievedChunks: 2, contextChars: 16, retrievalHits: [{ title: 'Unused candidate', preview: 'Other steps', usedInContext: false }] };
function beforeParse(window: Window) {
  Object.assign(window, { pawAgentUI: { mount: (options: object) => { Object.assign(window, { agentTestControls: options }); return ({ ready: Promise.resolve(), selection: () => undefined,
    setBusy: () => undefined, failure: () => undefined }); } } });
}
function mount() {
  const dom = new JSDOM(template.replace('body data-knowledge="false"', 'body data-knowledge="true"'), { runScripts: 'dangerously', url: 'http://localhost', beforeParse });
  const element = (id: string) => dom.window.document.getElementById(id)!;
  const question = element('question') as HTMLTextAreaElement; question.value = 'Actual question';
  return { dom, element, question };
}

describe('portable App interaction starter', () => {
  it('keeps first citation numbers for repeated document chunks and labels retrieval completion accurately', async () => {
    const { dom, element, question } = mount();
    try {
      const chunks = [sources[0], { sourceId: 'notebook', title: 'Licensed under the Apache License, Version 2.0', uri: 'https://example.test/Training_patches.ipynb', text: 'Notebook steps.' }, { ...sources[0], text: 'Additional evidence.' }];
      let finish!: (result: object) => void;
      Object.assign(dom.window, { pawApp: { invoke: () => new Promise((resolve) => { finish = resolve; }), history: async () => [] } });
      element('search-button').click();
      expect(element('answer-title').textContent).toBe('正在检索 · 尚未完成');
      expect(element('answer').textContent).toBe('正在查找相关资料…');
      await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
      finish({ sources: chunks, knowledge }); await vi.waitFor(() => expect(question.readOnly).toBe(false));
      expect([...dom.window.document.querySelectorAll('.source-number')].map((item: Element) => item.textContent)).toEqual(['1', '2']);
      expect(dom.window.document.querySelector('.source-chips')!.textContent).toContain('Training patches.ipynb');
      expect(element('status').textContent).toBe('检索已完成');
      expect(element('process').textContent).not.toContain('回答已完成');
      (dom.window.document.querySelector('.source-chip') as HTMLButtonElement).click();
      expect(element('sources').textContent).toContain('Supported steps.');
      expect(element('sources').textContent).toContain('Additional evidence.');
    } finally { dom.window.close(); }
  });
  it('shows sources while thinking, keeps open evidence during output, and waits for settlement', async () => {
    const { dom, element, question } = mount();
    try {
      let progress!: (value: object) => void; let finish!: (value: object) => void;
      const invoke = vi.fn((_action, _input, options) => { progress = options.onProgress; return new Promise((resolve) => { finish = resolve; }); });
      Object.assign(dom.window, { pawApp: { invoke, history: async () => [] } });
      element('answer-button').click(); element('answer-button').click();
      await vi.waitFor(() => expect(invoke).toHaveBeenCalledTimes(1)); expect(question.readOnly).toBe(true);
      progress({ stage: 'thinking', sources, knowledge });
      expect(element('status').textContent).toBe('正在分析问题');
      expect(dom.window.document.querySelector('.source-chips')!.textContent).toContain('Real manual');
      (dom.window.document.querySelector('.source-chip') as HTMLButtonElement).click();
      expect(element('sources').textContent).toContain('Real manual'); expect(element('sources').textContent).toContain('Unused candidate');
      const detail = element('sources').querySelector('details')!; detail.open = true;
      progress({ stage: 'answering', sources, knowledge, text: 'Partial answer' });
      expect(element('sources').querySelector('details')).toBe(detail); expect(detail.open).toBe(true);
      expect(element('answer-title').textContent).toContain('尚未完成'); expect(element('answer').textContent).toContain('Partial answer');
      finish({ text: 'Final answer', sources, knowledge }); await vi.waitFor(() => expect(question.readOnly).toBe(false));
      expect(element('status').textContent).toContain('回答已完成'); expect(element('answer').textContent).toBe('Final answer'); expect(question.readOnly).toBe(false);
    } finally { dom.window.close(); }
  });
  it('preserves failed input and evidence and restores history without a new call or stale error style', async () => {
    const { dom, element, question } = mount();
    try {
      const invoke = vi.fn(async (_action, _input, options) => { options.onProgress({ stage: 'sources_ready', sources, knowledge }); throw Object.assign(new Error('Configuration missing'), { state: 'failed' }); });
      Object.assign(dom.window, { pawApp: { invoke, history: async () => [{ state: 'completed', actionId: 'answer', input: { question: 'Saved question' }, result: { text: 'Saved answer', sources, knowledge } }] } });
      element('answer-button').click(); await vi.waitFor(() => expect(element('status').classList.contains('error')).toBe(true));
      expect(question.value).toBe('Actual question');
      (dom.window.document.querySelector('.source-chip') as HTMLButtonElement).click();
      expect(element('sources').textContent).toContain('Real manual');
      expect(element('status').classList.contains('error')).toBe(true); expect(element('elapsed').classList.contains('hidden')).toBe(true);
      element('history-toggle').click(); await vi.waitFor(() => expect(element('history-list').querySelector('button')).not.toBeNull()); element('history-list').querySelector('button')!.click();
      expect(question.value).toBe('Saved question'); expect(element('answer').textContent).toBe('Saved answer');
      expect(element('status').classList.contains('error')).toBe(false); expect(invoke).toHaveBeenCalledTimes(1);
    } finally { dom.window.close(); }
  });

  it('keeps a real conversation, renders code safely, and waits for cancellation settlement', async () => {
    // The producer must declare this field in app.json before enabling it.
    const page = new JSDOM(template.replace('data-context-key=""', 'data-context-key="conversation"'), { runScripts: 'dangerously', url: 'http://localhost', beforeParse });
      try {
        const get = (id: string) => page.window.document.getElementById(id)!;
        const input = get('question') as HTMLTextAreaElement;
        let progress!: (value: object) => void; let reject!: (error: Error) => void; let signal!: AbortSignal;
        const invoke = vi.fn().mockResolvedValueOnce({ text: '## 第一步\n```javascript\nMap.addLayer(image);\n```\n<img src=x onerror=alert(1)>' })
          .mockImplementationOnce((_action, _values, options) => { signal = options.signal; progress = options.onProgress; return new Promise((_resolve, fail) => { reject = fail; }); });
        Object.assign(page.window, { pawApp: { capabilities: { cancel: true }, invoke, history: async () => [] } });
        input.value = '怎样显示影像？'; get('answer-button').click();
        await vi.waitFor(() => expect(input.readOnly).toBe(false));
        expect(get('answer').querySelector('pre code')!.textContent).toBe('Map.addLayer(image);');
        expect(get('answer').querySelector('img')).toBeNull();
        input.value = '接下来呢？'; get('answer-button').click();
        expect(page.window.document.querySelectorAll('.turn')).toHaveLength(2);
        await vi.waitFor(() => expect(invoke).toHaveBeenCalledTimes(2));
        expect(invoke.mock.calls[1]![1]).toMatchObject({ question: '接下来呢？' });
        expect(JSON.parse(invoke.mock.calls[1]![1].conversation)).toEqual([expect.objectContaining({ question: '怎样显示影像？' })]);
        progress({ stage: 'answering', text: '{"decision":"先检查影像的波段' });
        expect(get('answer').textContent).toContain('先检查影像的波段');
        expect(get('answer').textContent).not.toContain('{"decision"');
        get('stop-button').click(); expect(signal.aborted).toBe(true); expect(input.readOnly).toBe(true);
        reject(Object.assign(new Error('已停止输出'), { state: 'cancelled' }));
        await vi.waitFor(() => expect(input.readOnly).toBe(false));
        expect(get('answer').textContent).toContain('先检查影像的波段');
        expect(input.value).toBe('接下来呢？'); expect(get('process').dataset.running).toBe('false');
        expect(invoke).toHaveBeenCalledTimes(2);
      } finally { page.window.close(); }
  });
  it('keeps the reconciled answer in the next follow-up context without retrying the original prompt', async () => {
    const dom = new JSDOM(template.replace('data-context-key=""', 'data-context-key="conversation"'), { runScripts: 'dangerously', url: 'http://localhost', beforeParse });
    try {
      const get = (id: string) => dom.window.document.getElementById(id)!;
      const question = get('question') as HTMLTextAreaElement;
      const invoke = vi.fn().mockRejectedValueOnce(Object.assign(new Error('connection lost'), { state: 'unconfirmed', requestId: 'original-request' }))
        .mockResolvedValueOnce({ text: 'Follow-up answer' });
      const reconcile = vi.fn(async () => ({ state: 'completed', result: { text: 'Recovered answer' } }));
      Object.assign(dom.window, { pawApp: { invoke, reconcile, history: async () => [] } });
      question.value = 'Original question'; get('answer-button').click();
      await vi.waitFor(() => expect(question.readOnly).toBe(false));
      await dom.window.agentTestControls.onCheck();
      expect(reconcile).toHaveBeenCalledWith('original-request'); expect(invoke).toHaveBeenCalledTimes(1);
      question.value = 'Follow-up'; get('answer-button').click();
      await vi.waitFor(() => expect(invoke).toHaveBeenCalledTimes(2));
      expect(JSON.parse(invoke.mock.calls[1]![1].conversation)).toEqual([{ question: 'Original question', answer: 'Recovered answer' }]);
    } finally { dom.window.close(); }
  });

});
