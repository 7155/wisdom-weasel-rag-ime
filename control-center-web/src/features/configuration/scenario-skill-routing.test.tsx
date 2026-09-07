import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlPathId } from '@/platform/routes';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { ConfigurationFeature } from '.';
import { ScenarioSkillSettings } from './ScenarioSkillSettings';

const scenarios = ['ordinary', 'room', 'trace', 'agentLab'] as const;
type Scenario = (typeof scenarios)[number];
type Routing = Record<Scenario, string[]>;

afterEach(cleanup);

it('isolates Trace Skills and preserves unavailable names in a scoped save', async () => {
  const user = userEvent.setup();
  let revision = 7;
  let routing: Routing = {
    ordinary: ['systematic-debugging'],
    room: ['facilitate-room', 'systematic-debugging'],
    trace: ['removed-but-configured', 'trace-agent-diagnostics'],
    agentLab: ['agent-eval-room-optimizer', 'systematic-debugging'],
  };
  const configurationResponse = () => ({
    ok: true,
    configuration: {
      revision,
      configuration: { skillRouting: routing },
    },
  });
  const transport = new MockControlTransport({
    capabilities: {
      routeIds: [
        'configuration.settings',
        'configuration.schema',
        'agent.subagents.templates',
        'agent.configuration.get',
        'agent.configuration.update',
        'agent.extensions.skills.list',
      ] as ControlPathId[],
    },
    routes: {
      'configuration.settings': {
        ok: true,
        settings: {},
        runtimeConfig: { runtimeRevision: 12 },
      },
      'configuration.schema': { ok: true, sections: [] },
      'agent.subagents.templates': { ok: true, items: [], maxParallel: 2, maxDepth: 2 },
      'agent.configuration.get': configurationResponse,
      'agent.configuration.update': (request: ControlRequest) => {
        const body = request.body as {
          changes: Record<string, string[]>;
          expectedRevision: number;
        };
        routing = {
          ...routing,
          trace: [...body.changes['skillRouting.trace']!],
        };
        revision += 1;
        return configurationResponse();
      },
      'agent.extensions.skills.list': {
        schemaVersion: 'rag-ime.skill-inventory.v1',
        ok: true,
        runtimeAvailable: true,
        revision: 'sha256:skills',
        items: [
          skill('systematic-debugging'),
          skill('facilitate-room'),
          skill('trace-agent-diagnostics'),
          skill('agent-eval-room-optimizer'),
        ],
      },
    },
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  render(
    <MemoryRouter>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}>
            <ConfigurationFeature />
          </QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );

  expect(await screen.findByRole('heading', { name: '技能加载', level: 2 })).toBeInTheDocument();
  const scenarioTabs = await screen.findByRole('tablist', { name: '技能加载场景' });
  expect(within(scenarioTabs).getByRole('tab', { name: /普通对话/ })).toBeInTheDocument();
  expect(within(scenarioTabs).getByRole('tab', { name: /Room 会话/ })).toBeInTheDocument();
  expect(within(scenarioTabs).getByRole('tab', { name: /Trace Agent/ })).toBeInTheDocument();
  expect(within(scenarioTabs).getByRole('tab', { name: /Agent Lab/ })).toBeInTheDocument();

  await user.click(within(scenarioTabs).getByRole('tab', { name: /Trace Agent/ }));
  const tracePanel = screen.getByRole('tabpanel', { name: /Trace Agent/ });
  const requiredTraceSkill = within(tracePanel).getByRole('switch', { name: /运行诊断/ });
  expect(requiredTraceSkill).toBeChecked();
  expect(requiredTraceSkill).toBeDisabled();
  expect(within(tracePanel).queryByRole('switch', { name: /Room 协作主持/ })).not.toBeInTheDocument();
  expect(within(tracePanel).queryByRole('switch', { name: /实验执行/ })).not.toBeInTheDocument();
  expect(within(tracePanel).getByText(/1 个已配置名称当前不在唯一可用清单中/)).toBeInTheDocument();

  await user.click(within(tracePanel).getByRole('switch', { name: /故障定位/ }));
  await user.click(within(tracePanel).getByRole('button', { name: '保存 Trace Agent 技能加载' }));

  await waitFor(() => expect(transport.requests.find(
    ({ request }) => request.pathId === 'agent.configuration.update',
  )?.request.body).toEqual({
    expectedRevision: 7,
    changes: {
      'skillRouting.trace': [
        'removed-but-configured',
        'systematic-debugging',
        'trace-agent-diagnostics',
      ],
    },
    updatedBy: 'settings-ui',
  }));
  expect(await within(tracePanel).findByText('Trace Agent 技能加载已保存')).toBeInTheDocument();
});

function skill(name: string) {
  return {
    skillId: name,
    name,
    description: `${name} description`,
    sourceKind: 'bundled',
    resourcePath: `skills/${name}/SKILL.md`,
    enabled: null,
    installed: true,
    installState: 'bundled',
    digest: `sha256:${name}`,
    contentRevision: `sha256:${name}`,
    sizeBytes: 128,
    management: 'inspect_only',
    managementReason: 'bundled',
    actions: [],
  };
}


it('searches skill purposes while preserving hidden selections in the saved scenario', async () => {
  const user = userEvent.setup();
  const transport = renderScenarioSkills();
  await user.type(await screen.findByRole('textbox', { name: '搜索技能' }), '网页');
  expect(screen.queryByRole('switch', { name: /故障定位/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole('switch', { name: /网页操作/ }));
  await user.click(screen.getByRole('button', { name: '保存 普通对话 技能加载' }));
  await waitFor(() => expect(transport.requests.find(({ request }) => request.pathId === 'agent.configuration.update')?.request.body).toEqual({
    expectedRevision: 7,
    changes: { 'skillRouting.ordinary': ['ego-browser', 'removed-but-configured', 'systematic-debugging'] },
    updatedBy: 'settings-ui',
  }));
  await user.clear(screen.getByRole('textbox', { name: '搜索技能' }));
  await user.click(screen.getByRole('combobox', { name: '筛选技能' }));
  await user.click(screen.getByRole('option', { name: '场景必需' }));
  expect(screen.getByText('没有匹配的技能')).toBeVisible();
  await user.click(screen.getByRole('tab', { name: /Trace Agent/ }));
  expect(screen.getByRole('switch', { name: /运行诊断.*场景必需/ })).toBeDisabled();
  expect(screen.getByRole('switch', { name: /运行诊断.*场景必需/ })).toBeChecked();
});

it('loads the full original instruction only when opened and keeps the canonical skill identity', async () => {
  const user = userEvent.setup();
  const transport = renderScenarioSkills();
  const row = await screen.findByRole('article', { name: '故障定位' });
  expect(row).toHaveTextContent('先复现并定位故障原因，再验证修复');
  expect(row).not.toHaveTextContent('systematic-debugging description');
  expect(transport.requests.some(({ request }) => request.pathId === 'agent.extensions.skills.get')).toBe(false);
  await user.click(within(row).getByText('查看技能原文'));
  expect(await within(row).findByText('Complete original instruction beyond the inventory summary.')).toBeVisible();
  expect(row).toHaveTextContent('systematic-debugging');
  expect(transport.requests.find(({ request }) => request.pathId === 'agent.extensions.skills.get')?.request.query).toEqual({ skillId: 'skill:debug:exact' });
  expect(transport.requests.some(({ request }) => request.pathId === 'agent.configuration.update')).toBe(false);
  expect(screen.getByRole('article', { name: 'vendor-custom' })).toHaveTextContent('Author supplied description.');
});

it('lets an instruction read fail and retry without losing the scene selection', async () => {
  const user = userEvent.setup();
  let attempts = 0;
  const transport = renderScenarioSkills(() => {
    if (++attempts === 1) throw new Error('offline');
    return { ok: true, item: { body: 'Recovered original instruction.' } };
  });
  const row = await screen.findByRole('article', { name: '故障定位' });
  await user.click(within(row).getByText('查看技能原文'));
  expect(await within(row).findByText('技能原文暂时无法读取')).toBeVisible();
  expect(within(row).getByRole('switch')).toBeChecked();
  await user.click(within(row).getByRole('button', { name: '重试原文' }));
  expect(await within(row).findByText('Recovered original instruction.')).toBeVisible();
  expect(transport.requests.some(({ request }) => request.pathId === 'agent.configuration.update')).toBe(false);
});

function renderScenarioSkills(readBody = () => ({ ok: true, item: { body: 'Complete original instruction beyond the inventory summary.' } })) {
  let revision = 7;
  const routing: Routing = {
    ordinary: ['removed-but-configured', 'systematic-debugging'], room: ['facilitate-room'],
    trace: ['trace-agent-diagnostics'], agentLab: ['agent-eval-room-optimizer'],
  };
  const configuration = () => ({ ok: true, configuration: { revision, configuration: { skillRouting: routing } } });
  const routeIds = ['agent.configuration.get', 'agent.configuration.update', 'agent.extensions.skills.list', 'agent.extensions.skills.get'] as const;
  const transport = new MockControlTransport({ routes: {
    'agent.configuration.get': configuration,
    'agent.configuration.update': ({ body }: ControlRequest) => {
      const changes = (body as { changes: Record<string, string[]> }).changes;
      for (const scenario of scenarios) if (changes[`skillRouting.${scenario}`]) routing[scenario] = changes[`skillRouting.${scenario}`]!;
      revision += 1;
      return configuration();
    },
    'agent.extensions.skills.list': { schemaVersion: 'rag-ime.skill-inventory.v1', ok: true, runtimeAvailable: true, items: [
      { ...skill('systematic-debugging'), skillId: 'skill:debug:exact' }, skill('ego-browser'), skill('facilitate-room'),
      skill('trace-agent-diagnostics'), skill('agent-eval-room-optimizer'),
      { ...skill('vendor-custom'), sourceKind: 'project', description: 'Author supplied description.' },
    ] },
    'agent.extensions.skills.get': readBody,
  } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<TooltipProvider><QueryClientProvider client={client}>
    <ScenarioSkillSettings routeIds={routeIds} transport={transport} />
  </QueryClientProvider></TooltipProvider>);
  return transport;
}
