import { describe, expect, it } from 'vitest';
import type { PublicToolResultView } from '@/features/agent/timeline/public-tool-result';
import {
  roomPublicActivityText,
  roomPublicToolResultView,
} from './room-tool-presentation';

describe('roomPublicToolResultView', () => {
  it('keeps humane tool details while removing protocol metadata and machine paths', () => {
    const view = roomPublicToolResultView(toolView({
      summary: '已更新报告文件',
      fields: [
        { id: 'status', label: '状态', value: '已完成' },
        { id: 'receiptId', label: '回执', value: 'receipt-room-82' },
        { id: 'dispatchId', label: '来源', value: 'dispatch-room-83' },
        { id: 'rootId', label: '目标', value: 'root-room-84' },
        { id: 'contentHash', label: '哈希', value: `sha256:${'a'.repeat(64)}` },
        { id: 'file', label: '文件', value: '/Volumes/undo 4t/team/control-center-web/src/Report.tsx' },
      ],
      request: [
        { id: 'path', label: '目标', value: '/Users/alice/project/src/Report.tsx', code: true },
        {
          id: 'command',
          label: '命令',
          value: 'cat /Users/alice/project/src/Report.tsx --token sk-private-secret',
          code: true,
        },
        { id: 'query', label: '查询', value: '任务汇报' },
      ],
      output: {
        text: [
          '已更新 /Volumes/undo 4t/team/control-center-web/src/Report.tsx',
          'dispatchId: dispatch-room-report-7',
          '任务 dispatch-room-report-7 已完成',
        ].join('\n'),
        truncated: false,
        kind: 'text',
        title: '返回片段',
      },
    }));

    expect(view.fields).toEqual([
      { id: 'status', label: '状态', value: '已完成' },
      { id: 'file', label: '文件', value: 'Report.tsx' },
    ]);
    expect(view.request).toEqual([
      { id: 'path', label: '目标', value: 'Report.tsx', code: true },
      {
        id: 'command',
        label: '命令',
        value: 'cat …/Report.tsx --token [已隐藏的密钥]',
        code: true,
      },
      { id: 'query', label: '查询', value: '任务汇报' },
    ]);
    expect(view.output?.text).toBe('已更新 …/Report.tsx\n任务协作记录已完成');
    expect(JSON.stringify(view)).not.toContain('receipt-room-82');
    expect(JSON.stringify(view)).not.toContain('dispatch-room-83');
    expect(JSON.stringify(view)).not.toContain('root-room-84');
    expect(JSON.stringify(view)).not.toContain('/Volumes/undo 4t');
    expect(JSON.stringify(view)).not.toContain('/Users/alice');
    expect(JSON.stringify(view)).not.toContain('sk-private-secret');
  });

  it('drops opaque Room references instead of replacing them with vague filler', () => {
    const view = roomPublicToolResultView(toolView({
      fields: [
        { id: 'stateRevision', label: '状态版本', value: 'revision-18' },
        { id: 'evidenceRef', label: '验证依据', value: 'receipt-room-proof-18' },
        { id: 'targetParticipantRef', label: '下一位伙伴', value: 'participant-reviewer-4' },
        { id: 'postRef', label: '公开记录', value: 'post-room-result-8' },
        { id: 'canonicalTool', label: '规范工具', value: 'room_commit' },
        { id: 'settlementStaged', label: '结算状态', value: '已暂存' },
        { id: 'terminalForModelTurn', label: '模型轮次', value: '模型轮次已结束' },
      ],
    }));

    expect(view.fields).toEqual([]);
    expect(JSON.stringify(view)).not.toContain('第 18 版');
    expect(JSON.stringify(view)).not.toContain('验证依据已保留');
    expect(JSON.stringify(view)).not.toContain('participant-reviewer-4');
    expect(JSON.stringify(view)).not.toContain('receipt-room-proof-18');
  });

  it('does not expose a raw JSON return envelope', () => {
    const view = roomPublicToolResultView(toolView({
      summary: 'dispatchId: dispatch-room-report-7',
      output: {
        text: JSON.stringify({
          receiptId: 'receipt-room-82',
          contentHash: `sha256:${'b'.repeat(64)}`,
          result: { status: 'completed' },
        }),
        truncated: false,
        kind: 'text',
        title: '返回片段',
      },
    }));

    expect(view.summary).toBe('');
    expect(view.output).toBeUndefined();
  });

  it('sanitizes terminal channels with the same Room boundary as the combined output', () => {
    const view = roomPublicToolResultView(toolView({
      toolId: 'bash',
      output: {
        text: 'ok\nTOKEN=combined-secret',
        truncated: false,
        kind: 'terminal',
        title: '命令输出',
        channels: [
          {
            id: 'stdout',
            label: '标准输出',
            text: '已读取 /Users/alice/project/src/RoomTurn.tsx',
            truncated: false,
          },
          {
            id: 'stderr',
            label: '标准错误',
            text: 'Authorization: Bearer channel-secret',
            truncated: false,
          },
        ],
      },
    }));

    expect(view.output?.text).toBe('ok\nTOKEN=[已隐藏的密钥]');
    expect(view.output?.channels).toEqual([
      {
        id: 'stdout',
        label: '标准输出',
        text: '已读取 …/RoomTurn.tsx',
        truncated: false,
      },
      {
        id: 'stderr',
        label: '标准错误',
        text: 'Authorization: [已隐藏的密钥]',
        truncated: false,
      },
    ]);
    expect(JSON.stringify(view)).not.toMatch(/\/Users\/alice|combined-secret|channel-secret/u);
  });

  it('translates standalone internal protocol terms in public activity text', () => {
    const text = roomPublicActivityText(
      'Kernel 已从 Root 创建 Dispatch，Task 按 AC 完成并保存 Receipt ID。',
    );

    expect(text).toBe(
      '协作系统已从本轮工作创建执行安排，工作项按验收标准完成并保存验证记录。',
    );
    expect(text).not.toMatch(/Kernel|Root|Dispatch|Task|\bAC\b|Receipt ID/iu);
  });

  it('turns persisted Room protocol failures into a natural recovery message', () => {
    const text = roomPublicActivityText(
      '验收短名与当前工作卡片不一致，请重新读取 room_state',
    );

    expect(text).toBe(
      '提交的完成条件与当前任务不一致，伙伴会读取最新进度后重试。',
    );
    expect(text).not.toMatch(/验收短名|工作卡片|room_state/iu);
  });

  it('keeps protocol filtering deterministic across consecutive values', () => {
    expect([
      'dispatchId: dispatch-room-a',
      'dispatchId: dispatch-room-b',
      'dispatchId: dispatch-room-c',
    ].map(roomPublicActivityText)).toEqual(['', '', '']);
  });

  it('redacts ordinary tokens, headers, JSON keys, and URL query secrets without hiding usage prose', () => {
    const text = roomPublicActivityText([
      'TOKEN=plain-secret',
      '"token": "json-secret"',
      'cookie: session-secret',
      'Authorization: Bearer header-secret',
      'https://example.test/run?token=url-secret&mode=1',
      'token 用量',
    ].join(' '));

    expect(text).not.toMatch(/plain-secret|json-secret|session-secret|header-secret|url-secret/u);
    expect(text).toContain('TOKEN=[已隐藏的密钥]');
    expect(text).toContain('mode=1');
    expect(text).toContain('token 用量');
  });
});

function toolView(overrides: Partial<PublicToolResultView>): PublicToolResultView {
  return {
    toolId: 'workspace_edit',
    toolLabel: '项目工具',
    operation: 'edit',
    summary: '项目工具已完成',
    fields: [],
    request: [],
    artifacts: [],
    sources: [],
    ...overrides,
  };
}
