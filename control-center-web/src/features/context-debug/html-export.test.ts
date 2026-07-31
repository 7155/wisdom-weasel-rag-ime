import { describe, expect, it } from 'vitest';
import { buildContextDebugHtml } from './html-export';
import { normalizeDebugContextResponse } from './model';

describe('buildContextDebugHtml', () => {
  it('exports the exact Provider assembly for every model call', () => {
    const response = normalizeDebugContextResponse({
      available: true,
      sessionId: 'session-debug',
      turnId: 'turn-debug',
      context: {
        sessionId: 'session-debug',
        turnId: 'turn-debug',
        capturedAtMs: 100,
        updatedAtMs: 400,
        systemPrompt: '回合级旧提示词',
        model: { provider: 'openai-codex', name: 'GPT Test' },
        activeTools: ['read', 'bash'],
        toolSchemas: [{ name: '回合级旧工具' }],
        modelCalls: [
          {
            index: 1,
            capturedAtMs: 100,
            updatedAtMs: 200,
            completedAtMs: 200,
            contextMessages: [{ role: 'user', content: '旧消息快照' }],
            providerContext: {
              systemPrompt: '调用一的真实提示词',
              messages: [{ role: 'user', content: '读取项目' }],
              tools: [{ name: 'read', description: '读取文件' }],
            },
            contextDelta: {
              commonPrefixMessages: 0,
              removedMessageCount: 0,
              addedMessageCount: 1,
              addedMessages: [{ role: 'user', content: '读取项目' }],
            },
            providerExchanges: [{ index: 1, capturedAtMs: 120, payload: { model: 'gpt-test', input: '读取项目' } }],
            assistantMessage: { role: 'assistant', content: [{ type: 'toolCall', name: 'read' }] },
          },
          {
            index: 2,
            capturedAtMs: 300,
            updatedAtMs: 400,
            completedAtMs: 400,
            contextMessages: [],
            providerContext: {
              systemPrompt: '调用二的真实提示词',
              messages: [
                { role: 'compactionSummary', content: '保留最初交接与已验证结果' },
                { role: 'toolResult', content: '已读取 README' },
              ],
              tools: [{ name: 'bash', description: '执行命令' }],
            },
            contextDelta: {
              baseCallIndex: 1,
              commonPrefixMessages: 0,
              removedMessageCount: 1,
              addedMessageCount: 2,
              addedMessages: [{ role: 'compactionSummary', content: '保留最初交接与已验证结果' }],
            },
            providerExchanges: [{ index: 2, capturedAtMs: 320, payload: { model: 'gpt-test', input: '已读取 README' } }],
            assistantMessage: { role: 'assistant', content: '完成' },
          },
        ],
        toolExecutions: [
          {
            toolCallId: 'tool-read',
            toolName: 'read',
            modelCallIndex: 1,
            startedAtMs: 130,
            endedAtMs: 180,
            startSequence: 1,
            endSequence: 2,
            args: { path: 'README.md' },
            result: { content: '项目说明' },
            status: 'completed',
            updates: [],
          },
        ],
        toolBatches: [{
          id: 'batch-1',
          modelCallIndex: 1,
          stage: 1,
          executionMode: 'parallel',
          startedAtMs: 130,
          endedAtMs: 180,
          status: 'completed',
          toolCallIds: ['tool-read'],
        }],
      },
    });

    const html = buildContextDebugHtml({
      generatedAtMs: 500,
      response,
      sessionTitle: '上下文验收',
    });

    expect(html).toContain('模型调用 1');
    expect(html).toContain('模型调用 2');
    expect(html).toContain('调用一的真实提示词');
    expect(html).toContain('调用二的真实提示词');
    expect(html).toContain('保留最初交接与已验证结果');
    expect(html).toContain('压缩摘要');
    expect(html).toContain('&quot;name&quot;: &quot;read&quot;');
    expect(html).toContain('&quot;name&quot;: &quot;bash&quot;');
    expect(html).toContain('README.md');
    expect(html).toContain('记录为并行批次 1 项');
    expect(html).toContain('记录模式不等同于已证明的实际时间重叠');
    expect(html.match(/回合级旧提示词/g)).toHaveLength(1);
    expect(html.match(/回合级旧工具/g)).toHaveLength(1);

    const document = new DOMParser().parseFromString(html, 'text/html');
    const callSections = document.querySelectorAll('.model-call');
    expect(callSections).toHaveLength(2);
    expect(callSections[0]?.textContent).toContain('调用一的真实提示词');
    expect(callSections[0]?.textContent).not.toContain('调用二的真实提示词');
    expect(callSections[1]?.textContent).toContain('调用二的真实提示词');
    expect(callSections[1]?.querySelector('[data-kind="compaction"]')).not.toBeNull();
    expect(document.querySelector('iframe')).toBeNull();

    const previewHtml = buildContextDebugHtml({
      generatedAtMs: 500,
      reportScriptSrc: 'http://control-center.test/context-debug-report.js',
      response,
      sessionTitle: '上下文验收',
    });
    expect(previewHtml).toContain('<script src="http://control-center.test/context-debug-report.js"></script>');
    expect(previewHtml).not.toContain("document.getElementById('expand').addEventListener");
  });

  it('labels legacy turn-level fallbacks as non-exact evidence', () => {
    const response = normalizeDebugContextResponse({
      available: true,
      context: {
        sessionId: 'session-legacy',
        turnId: 'turn-legacy',
        systemPrompt: '只有回合级提示词',
        toolSchemas: [{ name: 'legacy-tool' }],
        modelCalls: [{
          index: 1,
          contextMessages: [],
          providerContext: {},
          contextDelta: {},
        }],
      },
    });

    const html = buildContextDebugHtml({ response });

    expect(html).toContain('这条历史记录没有逐次模型服务快照');
    expect(html).toContain('不能作为当次实际请求的精确证据');
  });
});
