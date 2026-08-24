import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ObservationEventV1 } from '@/contracts/generated/observation-event.v1';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { ObservabilityFeature } from '.';

afterEach(cleanup);

describe('ObservabilityFeature', () => {
  it('loads a scoped snapshot, subscribes from its cursor, and merges live events', async () => {
    const transport = observationTransport();
    renderFeature(transport, '/observability?sessionId=session-a');

    expect(await screen.findByRole('heading', { name: '运行记录' })).toBeInTheDocument();
    const timeline = await screen.findByRole('list', { name: '运行记录事件' });
    expect(within(timeline).getByText('记忆工具 已完成')).toBeInTheDocument();
    expect(screen.getByText('运行记录只保存状态、耗时、数量和脱敏后的标识。', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('开启“本机上下文快照”后', { exact: false })).toBeInTheDocument();
    expect(screen.queryByText('PRIVATE_TOOL_RESULT')).not.toBeInTheDocument();

    await waitFor(() => expect(transport.subscriptionCalls).toHaveLength(1));
    expect(transport.requests[0]?.request).toEqual(expect.objectContaining({
      pathId: 'observability.snapshot',
      query: { limit: 300, sessionId: 'session-a' },
    }));
    expect(transport.subscriptionCalls[0]?.request).toEqual({
      pathId: 'observability.events',
      query: { sessionId: 'session-a' },
      lastEventId: 'observation:2',
    });

    expect(transport.emit('observability.events', observationEvent({
      sequence: 3,
      category: 'memory',
      phase: 'draft_ready',
      status: 'waiting',
      summary: '记忆整理草案已生成，等待审阅',
    }))).toBe(1);
    await waitFor(() => {
      expect(
        within(timeline).getByText('记忆整理草案已生成，等待审阅'),
      ).toBeInTheDocument();
    });
  });

  it('switches categories and exposes a causal trace without rendering raw attributes', async () => {
    const user = userEvent.setup();
    const transport = observationTransport();
    renderFeature(transport);

    const timeline = await screen.findByRole('list', { name: '运行记录事件' });
    expect(within(timeline).getByText('记忆工具 已完成')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '工具' }));

    await waitFor(() => {
      const latest = transport.requests.at(-1)?.request;
      expect(latest?.pathId).toBe('observability.snapshot');
      expect(latest?.query).toEqual({ limit: 300, category: 'tool' });
    });

    await user.click(within(timeline).getByText('记忆工具 已完成'));
    expect(screen.getByText('参数字段')).toBeInTheDocument();
    expect(screen.getByText('已脱敏')).toBeInTheDocument();
    expect(screen.queryByText('PRIVATE_TOOL_RESULT')).not.toBeInTheDocument();

    await user.type(screen.getByRole('searchbox', { name: '搜索运行记录' }), '不会匹配');
    expect(await screen.findByRole('heading', { name: '没有匹配的记录' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '清除筛选' }));
    expect((await screen.findAllByText('记忆工具 已完成')).length).toBeGreaterThan(0);
  });

  it('stays truthful about connection state, status tones, and step timing', async () => {
    const transport = observationTransport();
    renderFeature(transport);

    const timeline = await screen.findByRole('list', { name: '运行记录事件' });
    await waitFor(() => expect(transport.subscriptionCalls).toHaveLength(1));

    const pulse = document.querySelector('.observation-pulse') as HTMLElement;
    expect(pulse).toHaveAttribute('data-connection', 'live');
    expect(screen.getByText('实时')).toBeInTheDocument();
    expect(screen.queryByText(/快照生成于/)).not.toBeInTheDocument();

    const runningBadge = screen.getByText('运行中', { selector: '.mgmt-status' });
    expect(runningBadge).toHaveAttribute('data-tone', 'info');
    const runningRow = within(timeline).getByText('伙伴 正在分析').closest('li');
    expect(runningRow).toHaveAttribute('data-status', 'running');

    const stepTimes = document.querySelectorAll('.observation-trace__summary > time');
    expect(stepTimes).toHaveLength(2);
    expect(stepTimes[0]).toHaveAttribute('datetime', new Date(1_001).toISOString());

    expect(transport.fail('observability.events', new Error('stream down'))).toBe(1);
    await waitFor(() => expect(pulse).toHaveAttribute('data-connection', 'offline'));
    expect(screen.getByText('快照模式')).toBeInTheDocument();
    expect(screen.getByText(/快照生成于/)).toBeInTheDocument();
    expect(screen.getByText('实时事件暂时不可用，正在保留当前快照并尝试重连。')).toBeInTheDocument();
  });

  it('names a truncated snapshot and progressively reveals complete facts and real tool progress', async () => {
    const user = userEvent.setup();
    const item = observationEvent({
      sequence: 9,
      category: 'tool',
      phase: 'tool_progress',
      status: 'running',
      summary: '已扫描 24 / 48 段',
      durationMs: 1_420,
      attributes: { model: 'gpt-test', provider: 'openai' },
      metrics: {
        progressCurrent: 24,
        progressTotal: 48,
        argumentFieldCount: 2,
        resultFieldCount: 4,
        evidenceCount: 7,
        candidateCount: 9,
        eventCount: 12,
        compactionCount: 1,
      },
    });
    renderFeature(observationTransport({ items: [item], total: 48, truncated: true }));

    expect(await screen.findByText('当前显示最近 1 / 共 48 条')).toBeVisible();
    const progress = screen.getByRole('progressbar', { name: '工具进度 24 / 48' });
    expect(progress).toHaveAttribute('value', '24');
    expect(progress).toHaveAttribute('max', '48');

    const disclosure = screen.getByText(/查看其余 \d+ 项事实/).closest('summary') as HTMLElement;
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    const reveal = document.getElementById(disclosure.getAttribute('aria-controls') ?? '') as HTMLElement;
    expect(reveal).toHaveAttribute('aria-hidden', 'true');
    expect(reveal).toHaveAttribute('inert');
    await user.click(disclosure);
    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    expect(reveal).toHaveAttribute('aria-hidden', 'false');
    expect(reveal).not.toHaveAttribute('inert');
    disclosure.focus();
    await user.keyboard('{Enter}');
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    expect(reveal).toHaveAttribute('aria-hidden', 'true');
    expect(reveal).toHaveAttribute('inert');
    expect(reveal).toHaveTextContent('压缩次数');
  });
});

function renderFeature(
  transport: MockControlTransport,
  initialEntry = '/observability',
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <ObservabilityFeature />
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>
    </MemoryRouter>,
  );
}

function observationTransport(options: {
  items?: ObservationEventV1[];
  total?: number;
  truncated?: boolean;
} = {}): MockControlTransport {
  return new MockControlTransport({
    routes: {
      'observability.snapshot': (request: ControlRequest) => {
        const category = String(request.query?.category ?? '');
        const items = (options.items ?? [
          observationEvent({
            sequence: 2,
            category: 'tool',
            phase: 'tool_finished',
            status: 'completed',
            summary: 'ime.memory 已完成',
            durationMs: 48,
            metrics: { argumentFieldCount: 2, resultFieldCount: 4 },
            attributes: { rawTextStored: false, result: 'PRIVATE_TOOL_RESULT' },
          }),
          observationEvent({
            sequence: 1,
            category: 'agent',
            phase: 'status_changed',
            status: 'running',
            summary: 'Agent 正在分析',
          }),
        ]).filter((item) => !category || item.category === category);
        return {
          schemaVersion: 'rag-ime.observation-snapshot.v1',
          generatedAtMs: 1_000,
          firstSequence: 1,
          lastSequence: 2,
          resumeToken: 'observation:2',
          truncated: options.truncated ?? false,
          filters: {},
          counts: { total: options.total ?? items.length, byCategory: {}, byStatus: {} },
          items,
        };
      },
    },
  });
}

function observationEvent(
  overrides: Partial<ObservationEventV1> & Pick<
    ObservationEventV1,
    'sequence' | 'category' | 'phase' | 'status' | 'summary'
  >,
): ObservationEventV1 {
  return {
    schemaVersion: 'rag-ime.observation-event.v1',
    eventType: 'observation',
    eventId: `observation:test:${overrides.sequence}`,
    sequence: overrides.sequence,
    resumeToken: `observation:${overrides.sequence}`,
    traceId: 'trace:turn:test',
    spanId: `span:test:${overrides.sequence}`,
    parentSpanId: overrides.sequence > 1 ? 'span:test:1' : '',
    sessionId: 'session-a',
    roomId: '',
    turnId: 'turn-a',
    runId: '',
    category: overrides.category,
    phase: overrides.phase,
    name: overrides.phase,
    status: overrides.status,
    summary: overrides.summary,
    createdAtMs: 1_000 + overrides.sequence,
    startedAtMs: 1_000 + overrides.sequence,
    endedAtMs: overrides.status === 'completed' ? 1_000 + overrides.sequence : null,
    durationMs: overrides.durationMs ?? null,
    privacyClass: 'redacted',
    metrics: overrides.metrics ?? {},
    attributes: overrides.attributes ?? {},
    refs: [],
  };
}
