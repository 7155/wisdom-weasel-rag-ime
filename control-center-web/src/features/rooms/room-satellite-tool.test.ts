import { describe, expect, it } from 'vitest';
import { roomSatelliteToolContent, roomSatelliteToolMessage } from './room-satellite-tool';

describe('roomSatelliteToolContent', () => {
  it('expands a real write event into tool identity plus sanitized request and result detail', () => {
    const content = roomSatelliteToolContent({
      kind: 'participant_activity',
      status: 'completed',
      payload: {
        sourceEventType: 'tool_progress',
        toolName: 'write',
        arguments: { fileName: 'ROOT.md', path: 'docs/agent/ROOT.md' },
        result: { summary: 'ROOT.md +30', lineCount: 30, additions: 30 },
      },
    });

    expect(content).toBeDefined();
    expect(content!.label).toBe('写入文件');
    expect(content!.hasDetail).toBe(true);
    // The real change note survives Room sanitization; workspace paths and
    // protocol metadata do not.
    const serialized = JSON.stringify(content!.view);
    expect(serialized).toContain('+30');
    expect(serialized).not.toContain('docs/agent/ROOT.md');
    expect(serialized).not.toContain('toolCallId');
  });

  it('reads the agents delegate op from Room arguments and phrases the running line', () => {
    const content = roomSatelliteToolContent({
      kind: 'participant_activity',
      status: 'running',
      payload: {
        sourceEventType: 'tool_started',
        toolName: 'agents',
        arguments: { op: 'delegate' },
      },
    });

    expect(content!.label).toBe('多人协作');
    expect(content!.operation).toBe('委派协作任务');
    expect(roomSatelliteToolMessage(content!, 'running')).toBe('正在委派协作任务');
    expect(roomSatelliteToolMessage(content!, 'completed')).toBe('委派协作任务 · 已完成');
  });

  it('names Room-only tools without leaking a raw tool id chip', () => {
    const content = roomSatelliteToolContent({
      kind: 'participant_activity',
      status: 'running',
      payload: { sourceEventType: 'tool_started', toolName: 'room_partner' },
    });

    expect(content!.label).toBe('伙伴协作');
    expect(roomSatelliteToolMessage(content!, 'running')).toBe('正在使用「伙伴协作」');
  });

  it('leaves the seam open: no tool identity means no fabricated content', () => {
    expect(roomSatelliteToolContent({
      kind: 'participant_activity',
      status: 'running',
      payload: { sourceEventType: 'tool_started' },
    })).toBeUndefined();
  });

  it('keeps a bare lifecycle event collapsible-free instead of pretending it has detail', () => {
    const content = roomSatelliteToolContent({
      kind: 'participant_activity',
      status: 'completed',
      payload: { sourceEventType: 'tool_finished', toolName: 'skill_load', isError: false },
    });

    expect(content!.label).toBe('读取技能说明');
    expect(content!.hasDetail).toBe(false);
    expect(roomSatelliteToolMessage(content!, 'failed')).toBe('「读取技能说明」执行失败');
  });
});
