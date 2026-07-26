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
    expect(screen.getByText('原始提示词和消息正文不会写进运行记录。', { exact: false })).toBeInTheDocument();
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
    await user.click(screen.getByRole('tab', { name: '工具' }));

    await waitFor(() => {
      const latest = transport.requests.at(-1)?.request;
      expect(latest?.pathId).toBe('observability.snapshot');
      expect(latest?.query).toEqual({ limit: 300, category: 'tool' });
    });

    await user.click(within(timeline).getByText('记忆工具 已完成'));
    expect(screen.getByText('参数字段')).toBeInTheDocument();
    expect(screen.getByText('已脱敏')).toBeInTheDocument();
    expect(screen.queryByText('PRIVATE_TOOL_RESULT')).not.toBeInTheDocument();
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

function observationTransport(): MockControlTransport {
  return new MockControlTransport({
    routes: {
      'observability.snapshot': (request: ControlRequest) => {
        const category = String(request.query?.category ?? '');
        const items = [
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
        ].filter((item) => !category || item.category === category);
        return {
          schemaVersion: 'rag-ime.observation-snapshot.v1',
          generatedAtMs: 1_000,
          firstSequence: 1,
          lastSequence: 2,
          resumeToken: 'observation:2',
          truncated: false,
          filters: {},
          counts: { total: items.length, byCategory: {}, byStatus: {} },
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
