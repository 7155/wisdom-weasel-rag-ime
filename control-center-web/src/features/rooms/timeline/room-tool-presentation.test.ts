import { describe, expect, it } from 'vitest';
import type { PublicToolResultView } from '@/features/agent/timeline/public-tool-result';
import { roomPublicToolResultView } from './room-tool-presentation';

describe('roomPublicToolResultView', () => {
  it('keeps humane tool details while removing protocol metadata and machine paths', () => {
    const view = roomPublicToolResultView(toolView({
      summary: '已更新报告文件',
      fields: [
        { id: 'status', label: '状态', value: '已完成' },
        { id: 'receiptId', label: '回执', value: 'receipt-room-82' },
        { id: 'contentHash', label: '哈希', value: `sha256:${'a'.repeat(64)}` },
        { id: 'file', label: '文件', value: '/Volumes/undo 4t/team/control-center-web/src/Report.tsx' },
      ],
      request: [
        { id: 'path', label: '目标', value: '/Users/alice/project/src/Report.tsx', code: true },
        { id: 'command', label: '命令', value: 'cat /Users/alice/project/src/Report.tsx', code: true },
        { id: 'query', label: '查询', value: '任务汇报' },
      ],
      output: {
        text: [
          '已更新 /Volumes/undo 4t/team/control-center-web/src/Report.tsx',
          'dispatchId: dispatch-room-report-7',
          '任务 dispatch-room-report-7 已完成',
        ].join('\n'),
        truncated: false,
      },
    }));

    expect(view.fields).toEqual([
      { id: 'status', label: '状态', value: '已完成' },
      { id: 'file', label: '文件', value: 'Report.tsx' },
    ]);
    expect(view.request).toEqual([
      { id: 'path', label: '目标', value: 'Report.tsx', code: true },
      { id: 'query', label: '查询', value: '任务汇报' },
    ]);
    expect(view.output?.text).toBe('已更新 …/Report.tsx\n任务 协作记录 已完成');
    expect(JSON.stringify(view)).not.toContain('receipt-room-82');
    expect(JSON.stringify(view)).not.toContain('/Volumes/undo 4t');
    expect(JSON.stringify(view)).not.toContain('/Users/alice');
  });

  it('keeps semantic Room references readable without exposing their raw values', () => {
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

    expect(view.fields).toEqual([
      { id: 'stateRevision', label: '状态版本', value: '第 18 版' },
      { id: 'evidenceRef', label: '验证依据', value: '验证依据已保留' },
      { id: 'targetParticipantRef', label: '下一位伙伴', value: '目标伙伴已确认' },
      { id: 'postRef', label: '公开记录', value: '公开记录已保留' },
    ]);
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
      },
    }));

    expect(view.summary).toBe('项目工具已完成');
    expect(view.output).toBeUndefined();
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
    sources: [],
    ...overrides,
  };
}
