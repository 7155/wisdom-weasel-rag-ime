import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { AgentContextTraceV1 } from '@/contracts/generated/agent-context-trace.v1';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import {
  MemoryRecallReceipt,
  memoryRecallReceiptFromTrace,
} from './MemoryRecallReceipt';

describe('MemoryRecallReceipt', () => {
  it('projects only an included per-turn memory trace and starts folded', async () => {
    const receipt = memoryRecallReceiptFromTrace(memoryTrace());
    expect(receipt).toMatchObject({
      count: 3,
      durationMs: 18,
      nodeId: 'node-memory',
      traceId: 'trace-memory',
      turnId: 'turn-memory',
    });

    const openRoute = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <PawOsDesktopProvider openRoute={openRoute} openWindow={() => {}}>
        <MemoryRecallReceipt receipt={receipt!} />
      </PawOsDesktopProvider>,
    );

    const disclosure = container.querySelector('details');
    expect(disclosure).not.toHaveAttribute('open');
    expect(screen.getByText('记忆召回 · 3 条 · 18 ms')).toBeInTheDocument();
    expect(screen.queryByText('偏好：回答保持简洁')).not.toBeInTheDocument();

    await user.click(screen.getByText('记忆召回 · 3 条 · 18 ms'));
    expect(screen.getByText('偏好：回答保持简洁')).toBeInTheDocument();
    expect(screen.getByText('PAW 项目约定')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '在记忆中打开 atom-1' }));
    expect(openRoute).toHaveBeenCalledWith('/memory?layer=atoms&id=atom-1');
    await user.click(screen.getByRole('button', { name: '查看本轮上下文轨迹' }));
    expect(openRoute).toHaveBeenCalledWith('/agent?session=session-memory&trace=trace-memory&node=node-memory');
    await user.click(screen.getByRole('button', { name: '打开记忆召回设置' }));
    expect(openRoute).toHaveBeenCalledWith('/memory?view=preferences');
  });

  it('does not manufacture a receipt for omitted recall or missing hit count', () => {
    expect(memoryRecallReceiptFromTrace(memoryTrace({ disposition: 'omitted' }))).toBeUndefined();
    expect(memoryRecallReceiptFromTrace(memoryTrace({ hitCount: undefined }))).toBeUndefined();
  });
});

function memoryTrace(options: {
  disposition?: 'included' | 'omitted';
  hitCount?: number;
} = {}): AgentContextTraceV1 {
  const disposition = options.disposition ?? 'included';
  const hitCount = Object.hasOwn(options, 'hitCount') ? options.hitCount : 3;
  return {
    schemaVersion: 'rag-ime.agent-context-trace.v1',
    traceId: 'trace-memory',
    sessionId: 'session-memory',
    turnId: 'turn-memory',
    sourceKind: 'prompt',
    status: 'accepted',
    finalFingerprint: 'trace-fingerprint',
    nodes: [{
      nodeId: 'node-memory',
      ordinal: 2,
      stage: 'memory_recall',
      label: '当前回合个人记忆召回',
      sourceKind: 'memory_bootstrap',
      disposition,
      summary: '已装配个人记忆上下文',
      charCount: 120,
      tokenEstimate: 30,
      durationMs: 18,
      fingerprint: 'node-fingerprint',
      reason: '',
      metadata: {
        ...(hitCount === undefined ? {} : { hitCount }),
        memoryAtomIds: 'atom-1',
        memoryBookIds: 'book-2',
        sourceTitles: '偏好：回答保持简洁,PAW 项目约定',
      },
      createdAtMs: 1_010,
    }],
    edges: [],
    createdAtMs: 1_000,
    updatedAtMs: 1_020,
  };
}
