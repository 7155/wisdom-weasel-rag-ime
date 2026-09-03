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
  const requiredTraceSkill = within(tracePanel).getByRole('switch', { name: /trace-agent-diagnostics/ });
  expect(requiredTraceSkill).toBeChecked();
  expect(requiredTraceSkill).toBeDisabled();
  expect(within(tracePanel).queryByRole('switch', { name: /facilitate-room/ })).not.toBeInTheDocument();
  expect(within(tracePanel).queryByRole('switch', { name: /agent-eval-room-optimizer/ })).not.toBeInTheDocument();
  expect(within(tracePanel).getByText(/1 个已配置名称当前不在唯一可用清单中/)).toBeInTheDocument();

  await user.click(within(tracePanel).getByRole('switch', { name: /systematic-debugging/ }));
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
