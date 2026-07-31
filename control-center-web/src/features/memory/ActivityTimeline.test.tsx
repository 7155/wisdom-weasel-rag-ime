import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type {
  ControlRequest,
  ControlSubscription,
  ControlTransport,
} from '@/platform/transport';
import { ActivityTimeline } from './ActivityTimeline';

afterEach(cleanup);

describe('ActivityTimeline activity projection', () => {
  it('keeps a cross-app morning activity together and reveals its evidence chain', async () => {
    const user = userEvent.setup();
    renderTimeline(semanticTimeline());

    expect(await screen.findByText('2 项活动')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '上午' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '下午' })).toBeInTheDocument();

    const task = screen.getByRole('button', { name: '查看任务：切换 Codex 账号并继续开发' });
    expect(within(task).getByText('Terminal')).toBeInTheDocument();
    expect(within(task).getByText('Codex')).toBeInTheDocument();
    expect(within(task).getByText('8 条证据')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /查看任务：/ })).toHaveLength(2);

    await user.click(task);
    const dialog = await screen.findByRole('dialog', { name: '切换 Codex 账号并继续开发' });
    expect(within(dialog).getAllByText('通过 cas 切换到工作账号。')).toHaveLength(2);

    const eventSummary = within(dialog).getByText('事件 1').closest('summary');
    expect(eventSummary).not.toBeNull();
    await user.click(eventSummary!);
    const eventDetails = eventSummary!.closest('details');
    expect(eventDetails).not.toBeNull();

    const referenceSummary = within(eventDetails!).getByText('来源引用 · 1').closest('summary');
    expect(referenceSummary).not.toBeNull();
    await user.click(referenceSummary!);
    expect(within(eventDetails!).getByText(/input_events\/101/)).toBeVisible();
    expect(within(eventDetails!).getByText('Terminal 命令记录')).toBeVisible();

    await user.click(within(eventDetails!).getByRole('button', { name: /Terminal 命令记录/ }));
    const referenceDialog = await screen.findByRole('dialog', { name: 'Terminal 命令记录' });
    expect(within(referenceDialog).getByText('通过 cas 切换到工作账号。')).toBeVisible();
    expect(within(referenceDialog).getByRole('region', { name: '整理使用的输入上下文' })).toBeVisible();
    expect(within(referenceDialog).getByText('准备切换工作账号')).toBeVisible();
  });

  it('falls back to legacy segments and preserves expandable source event identities', async () => {
    const user = userEvent.setup();
    renderTimeline(legacyTimeline());

    expect(await screen.findByText('1 项活动')).toBeInTheDocument();
    expect(screen.queryByText('1 个时段')).not.toBeInTheDocument();
    const task = screen.getByRole('button', { name: /查看任务：实现旧时间线兼容/ });
    await user.click(task);

    const dialog = await screen.findByRole('dialog', { name: '实现旧时间线兼容' });
    const eventSummary = within(dialog).getByText('事件 1').closest('summary');
    expect(eventSummary).not.toBeNull();
    await user.click(eventSummary!);
    expect(within(dialog).getByText('原始事件 #201')).toBeInTheDocument();
    expect(within(dialog).getByText('当前接口未返回这条事件的来源引用。')).toBeVisible();
    expect(dialog).toHaveTextContent('分类未标注');
  });

  it('projects a minute-scale production fragment as ordinary activity with reference-only evidence', async () => {
    const user = userEvent.setup();
    renderTimeline(evidenceRefTimeline());

    expect(await screen.findByText('1 项活动')).toBeInTheDocument();
    const task = screen.getByRole('button', { name: '查看任务：切换账号并继续记忆系统开发' });
    expect(within(task).getByText('Terminal')).toBeInTheDocument();
    expect(within(task).getByText('Codex')).toBeInTheDocument();
    expect(within(task).getByText('2 条证据')).toBeInTheDocument();
    expect(within(task).getAllByText('普通活动').length).toBeGreaterThan(0);
    expect(within(task).queryByText('长时聚合')).not.toBeInTheDocument();

    await user.click(task);
    const dialog = await screen.findByRole('dialog', { name: '切换账号并继续记忆系统开发' });
    const firstEvent = within(dialog).getByText('事件 1').closest('summary');
    expect(firstEvent).not.toBeNull();
    await user.click(firstEvent!);
    const firstEventDetails = firstEvent!.closest('details');
    expect(firstEventDetails).not.toBeNull();
    expect(within(firstEventDetails!).getByText('当前接口只提供事件身份，未返回可展示的事件摘要。')).toBeVisible();
    expect(within(firstEventDetails!).getByRole('button', { name: '打开原始事件' })).toBeVisible();
  });

  it('groups a legacy task crossing noon as all-day and labels duration as a span', async () => {
    renderTimeline(crossPeriodTimeline());

    expect(await screen.findByRole('heading', { name: '全天' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '上午' })).not.toBeInTheDocument();
    expect(screen.getByText('首末证据跨度合计')).toBeInTheDocument();
    expect(screen.queryByText('活跃时长')).not.toBeInTheDocument();
    const task = screen.getByRole('button', { name: '查看任务：持续优化输入法记忆召回' });
    expect(within(task).getByText('长时聚合 · 首末证据跨度 6 小时')).toBeInTheDocument();
  });
});

function renderTimeline(timeline: Record<string, unknown>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={timelineTransport(timeline)}>
        <QueryClientProvider client={client}>
          <ActivityTimeline />
        </QueryClientProvider>
      </ControlTransportProvider>
    </TooltipProvider>,
  );
}

function timelineTransport(timeline: Record<string, unknown>): ControlTransport {
  return {
    kind: 'mock',
    capabilities: async () => ({
      schemaVersion: 'rag-ime.control-frontend-capabilities.v1',
      transport: 'mock',
      routeIds: [
        'memory.activityTimeline.get',
        'memory.activityTimeline.build',
        'memory.activityTimeline.approve',
        'memory.activityTimeline.reject',
        'memory.reference.get',
      ],
      features: {},
      native: {},
    }),
    request: async <Response,>(request: ControlRequest) => {
      if (request.pathId === 'memory.activityTimeline.get') {
        return { ok: true, timeline } as Response;
      }
      if (request.pathId === 'memory.reference.get') {
        return {
          ok: true,
          item: {
            id: String(request.params?.referenceId ?? ''),
            title: 'Terminal 命令记录',
            text: '通过 cas 切换到工作账号。',
            status: 'active',
            occurredAtMs: new Date(2026, 6, 18, 9, 0).getTime(),
            sourceContextAvailable: true,
            sourceContext: {
              recentContext: '准备切换工作账号',
              preedit: 'cas codex',
              redacted: false,
              scopeProject: 'wisdom-weasel-rag-ime',
              usedFor: ['source_fingerprint', 'semantic_grouping'],
            },
          },
          source: { kind: 'input_event', id: String(request.params?.referenceId ?? '') },
          evidenceRefs: [],
        } as Response;
      }
      throw new Error(`Unexpected request: ${request.pathId}`);
    },
    subscribe: (_request: ControlSubscription) => () => undefined,
  } as unknown as ControlTransport;
}

function semanticTimeline(): Record<string, unknown> {
  const start = new Date(2026, 6, 18, 9, 0).getTime();
  return {
    timelineId: 'timeline:semantic',
    date: '2026-07-18',
    timezone: 'Asia/Shanghai',
    status: 'draft',
    sourceEventHash: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    summary: '上午完成账号切换与连续开发，下午验证记忆召回。',
    eventCount: 12,
    segmentCount: 2,
    ordinaryActivityCount: 0,
    consolidatedActivityCount: 2,
    updatedAtMs: start + 8 * 3_600_000,
    semanticTasks: [
      {
        segmentId: 'semantic-task:account-and-codex',
        title: '切换 Codex 账号并继续开发',
        period: 'morning',
        startMs: start,
        endMs: start + 2 * 3_600_000,
        activityKind: 'consolidated_activity',
        summary: '在 Terminal 通过 cas 切换 Codex 账号，随后回到 Codex 延续同一项开发工作。',
        apps: [
          { bundleId: 'com.apple.Terminal', name: 'Terminal', eventCount: 2 },
          { bundleId: 'com.openai.codex', name: 'Codex', eventCount: 6 },
        ],
        eventCount: 8,
        evidenceCount: 8,
        sourceEventIds: [101, 102],
        sourceKinds: ['terminal', 'pi_agent'],
        contextGroupIds: ['group:memory-v2'],
        redactedEventCount: 0,
        events: [
          {
            eventId: 101,
            occurredAtMs: start,
            app: { bundleId: 'com.apple.Terminal', name: 'Terminal' },
            sourceKind: 'terminal',
            summary: '通过 cas 切换到工作账号。',
            redacted: false,
            sourceRefs: [
              {
                refId: 'input-event:101',
                kind: 'input_event',
                label: 'Terminal 命令记录',
                locator: 'input_events/101',
              },
            ],
          },
          {
            eventId: 102,
            occurredAtMs: start + 20 * 60_000,
            app: { bundleId: 'com.openai.codex', name: 'Codex' },
            sourceKind: 'pi_agent',
            summary: '继续完成语义时间线方案。',
            sourceRefs: [],
          },
        ],
      },
      {
        segmentId: 'semantic-task:verification',
        title: '验证三条记忆消费路径',
        period: 'afternoon',
        startMs: start + 5 * 3_600_000,
        endMs: start + 6.5 * 3_600_000,
        summary: '验证生成、会话首次注入和 Agent Tools 的召回。',
        activityKind: 'consolidated_activity',
        apps: [{ bundleId: 'com.mitchellh.ghostty', name: 'Ghostty', eventCount: 4 }],
        eventCount: 4,
        evidenceCount: 4,
        sourceEventIds: [201],
        redactedEventCount: 0,
        events: [],
      },
    ],
  };
}

function evidenceRefTimeline(): Record<string, unknown> {
  const start = new Date(2026, 6, 18, 9, 0).getTime();
  return {
    timelineId: 'timeline:evidence-refs',
    date: '2026-07-18',
    timezone: 'Asia/Shanghai',
    status: 'draft',
    sourceEventHash: 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
    summary: '上午围绕同一项记忆系统工作，在 Terminal 和 Codex 之间切换。',
    eventCount: 2,
    segmentCount: 1,
    ordinaryActivityCount: 1,
    consolidatedActivityCount: 0,
    updatedAtMs: start + 2 * 3_600_000,
    segments: [
      {
        segmentId: 'semantic-task:production-evidence-refs',
        title: '切换账号并继续记忆系统开发',
        startMs: start,
        endMs: start + 20 * 60_000,
        activityKind: 'ordinary_activity',
        summary: '通过 cas 切换账号后继续完成记忆系统开发。',
        apps: ['com.apple.Terminal', 'com.openai.codex'],
        eventCount: 2,
        evidenceRefs: [
          {
            sourceType: 'input_event',
            sourceId: 'event:501',
            eventId: 501,
            app: 'com.apple.Terminal',
            sourceKind: 'terminal',
            occurredAtMs: start,
            redacted: false,
          },
          {
            sourceType: 'input_event',
            sourceId: 'event:502',
            eventId: 502,
            app: 'com.openai.codex',
            sourceKind: 'pi_agent',
            occurredAtMs: start + 20 * 60_000,
            redacted: false,
          },
        ],
      },
    ],
  };
}

function crossPeriodTimeline(): Record<string, unknown> {
  const start = new Date(2026, 6, 18, 9, 0).getTime();
  return {
    timelineId: 'timeline:cross-period',
    date: '2026-07-18',
    timezone: 'Asia/Shanghai',
    status: 'draft',
    sourceEventHash: 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
    summary: '上午到下午持续优化输入法记忆召回。',
    eventCount: 2,
    segmentCount: 1,
    ordinaryActivityCount: 0,
    consolidatedActivityCount: 1,
    updatedAtMs: start + 6 * 3_600_000,
    segments: [
      {
        segmentId: 'semantic-task:cross-period',
        title: '持续优化输入法记忆召回',
        startMs: start,
        endMs: start + 6 * 3_600_000,
        activityKind: 'consolidated_activity',
        summary: '上午开始排查，下午完成验证。',
        apps: ['com.openai.codex'],
        eventCount: 2,
        sourceEventIds: [601, 602],
        redactedEventCount: 0,
      },
    ],
  };
}

function legacyTimeline(): Record<string, unknown> {
  const start = new Date(2026, 6, 18, 10, 0).getTime();
  return {
    timelineId: 'timeline:legacy',
    date: '2026-07-18',
    timezone: 'Asia/Shanghai',
    status: 'approved',
    sourceEventHash: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    summary: '旧时间线载荷仍然可以阅读。',
    eventCount: 1,
    segmentCount: 1,
    ordinaryActivityCount: 0,
    consolidatedActivityCount: 0,
    updatedAtMs: start,
    segments: [
      {
        segmentId: 'segment:legacy',
        app: 'com.openai.codex',
        sourceKinds: ['pi_agent'],
        contextGroupIds: ['group:compatibility'],
        startMs: start,
        endMs: start + 30 * 60_000,
        eventCount: 1,
        sourceEventIds: [201],
        summary: '实现旧时间线兼容。',
        redactedEventCount: 0,
      },
    ],
  };
}
