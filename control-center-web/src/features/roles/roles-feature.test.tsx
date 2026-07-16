import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { StubControlTransport } from '@/test/stub-control-transport';
import { previewPersonas, previewTemplates } from '@/features/agent/preview-data';
import { RolesFeature } from './index';

describe('Roles experience', () => {
  afterEach(cleanup);
  it('keeps Persona visuals separate from Agent Template runtime limits', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.subagents.templates': { ok: true, items: previewTemplates },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);
    expect(await screen.findByText('此刻陪你输入，也陪你把事情想清楚')).toBeInTheDocument();
    expect(screen.getAllByLabelText('角色阶段')[0]).toHaveTextContent('此刻阶段');
    expect(screen.getByText('陪伴阶段')).toBeInTheDocument();
    expect(screen.queryByText(/5\.6 (?:Luna|Terra|Sol)/)).not.toBeInTheDocument();
    expect(screen.getByText('温暖 · 证据优先')).toBeInTheDocument();
    expect(screen.queryByText('control-center-safe-v1')).not.toBeInTheDocument();
    expect(screen.queryByText('control-center-v1')).not.toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Agent 模板' }));
    expect(screen.getAllByText('研究员')).toHaveLength(2);
    expect(screen.getByText(/10 轮/)).toBeInTheDocument();
    expect(screen.getByText('只读资料与审阅工具')).toBeInTheDocument();
    expect(screen.getByText('独立上下文 · 继承当前上下文')).toBeInTheDocument();
    expect(screen.queryByText('subagent-readonly-v1')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /执行者/ }));
    expect(screen.getAllByText('执行者')).toHaveLength(2);
    expect(screen.getByText(/18 轮/)).toBeInTheDocument();
    expect(screen.getByText('受控执行工具')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '开始对话' })).not.toBeInTheDocument();
    await waitFor(() => expect(transport.requests.map((call) => call.request.pathId)).toEqual(expect.arrayContaining(['agent.roles.list', 'agent.subagents.templates'])));
  });

  it('creates a Session with the selected Persona and navigates to it', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.subagents.templates': { ok: true, items: previewTemplates },
      'agent.sessions.create': { ok: true, session: { id: 'session-past' } },
    } });
    render(
      <MemoryRouter initialEntries={['/roles']}>
        <ControlTransportProvider transport={transport}>
          <TooltipProvider><RolesFeature /><LocationProbe /></TooltipProvider>
        </ControlTransportProvider>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: /智鼬·初识/ }));
    await user.click(screen.getByRole('button', { name: '开始对话' }));

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/agent?session=session-past'));
    const create = transport.requests.find((call) => call.request.pathId === 'agent.sessions.create');
    expect(create?.request.body).toEqual({
      title: '智鼬·初识 对话',
      mode: 'assistant',
      roleId: 'hermes-v1',
      roleVersion: '1',
      workspaceRoots: [],
    });
  });

  it('persists a per-role default model and thinking level', async () => {
    const user = userEvent.setup();
    const configured = {
      ...previewPersonas[0]!,
      defaults: {
        ...previewPersonas[0]!.defaults,
        modelProfile: 'gpt/gpt-5.6-terra',
        thinkingLevel: 'low' as const,
      },
    };
    const updated = {
      ...configured,
      defaults: {
        ...configured.defaults,
        modelProfile: 'gpt/gpt-5.6-sol',
        thinkingLevel: 'xhigh' as const,
      },
    };
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: [configured] },
      'agent.subagents.templates': { ok: true, items: [] },
      'agent.role.models': {
        ok: true,
        providers: [{
          id: 'gpt',
          displayName: 'GPT',
          models: [
            { provider: 'gpt', id: 'gpt-5.6-terra', name: 'GPT-5.6 Terra', api: 'responses', reasoning: true, thinkingLevels: ['off', 'low', 'high'], supportsImages: true, contextWindow: 1000000, maxTokens: 128000 },
            { provider: 'gpt', id: 'gpt-5.6-sol', name: 'GPT-5.6 Sol', api: 'responses', reasoning: true, thinkingLevels: ['off', 'xhigh'], supportsImages: true, contextWindow: 1000000, maxTokens: 128000 },
          ],
        }],
      },
      'agent.role.runtimeDefaults.update': { ok: true, role: updated },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    await screen.findByText('GPT-5.6 Terra');
    await user.click(screen.getByLabelText('角色默认模型'));
    await user.click(await screen.findByRole('option', { name: 'GPT-5.6 Sol' }));
    await user.click(screen.getByLabelText('角色默认推理强度'));
    expect(await screen.findByRole('option', { name: '不启用推理' })).toBeInTheDocument();
    await user.click(await screen.findByRole('option', { name: '极高' }));
    await user.click(screen.getByRole('button', { name: '保存默认设置' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.role.runtimeDefaults.update')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.role.runtimeDefaults.update')?.request.body).toEqual({
      roleId: configured.roleId,
      roleVersion: configured.version,
      provider: 'gpt',
      modelId: 'gpt-5.6-sol',
      thinkingLevel: 'xhigh',
    });
    expect(screen.getByRole('status')).toHaveTextContent(`${configured.displayName} 的默认模型已保存。`);
  });

  it('does not substitute preview Personas when the native catalog is empty', async () => {
    const transport = new StubControlTransport('native', {
      'agent.roles.list': { ok: true, items: [] },
      'agent.subagents.templates': { ok: true, items: [] },
    });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect(await screen.findByText('本机还没有可用角色。')).toBeInTheDocument();
    expect(screen.queryByText('此刻陪你输入，也陪你把事情想清楚')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始对话' })).toBeDisabled();
  });

  it('keeps the real Persona catalog usable when the template request fails', async () => {
    const user = userEvent.setup();
    const transport = new StubControlTransport('native', {
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.subagents.templates': () => { throw new Error('template service unavailable'); },
    });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect(await screen.findByText('此刻陪你输入，也陪你把事情想清楚')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始对话' })).toBeEnabled();
    expect(screen.getByRole('status')).toHaveTextContent('Agent 模板：暂时无法读取，请稍后重试。');
    await user.click(screen.getByRole('button', { name: /智鼬·初识/ }));
    expect(screen.getByRole('status')).toHaveTextContent('Agent 模板：暂时无法读取，请稍后重试。');
    expect(transport.requests.map((request) => request.pathId)).toEqual([
      'agent.roles.list',
      'agent.subagents.templates',
      'agent.role.models',
    ]);
  });

  it('keeps real templates inspectable and disables the Persona action when roles fail', async () => {
    const user = userEvent.setup();
    const transport = new StubControlTransport('native', {
      'agent.roles.list': () => { throw new Error('role service unavailable'); },
      'agent.subagents.templates': { ok: true, items: previewTemplates },
    });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect(await screen.findByRole('status')).toHaveTextContent('角色目录：暂时无法读取，请稍后重试。');
    expect(screen.getByRole('button', { name: '开始对话' })).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: 'Agent 模板' }));
    expect(screen.getAllByText('研究员')).toHaveLength(2);
    expect(screen.getByText(/10 轮/)).toBeInTheDocument();
  });

  it('creates a user-defined role through the real role creation contract', async () => {
    const user = userEvent.setup();
    const createdRole = {
      ...previewPersonas[2],
      roleId: 'morning-guide-v1',
      displayName: '智鼬·晨光',
      tagline: '先看清今天，再稳稳向前',
      summary: '适合陪我整理早晨计划与关键证据。',
      traits: ['清晰', '温和'] as ['清晰', '温和'],
      defaults: {
        ...previewPersonas[2]!.defaults,
        modelPolicy: 'session-selected',
      },
      selectableModes: ['assistant', 'coordinator'] as ['assistant', 'coordinator'],
    };
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.subagents.templates': { ok: true, items: previewTemplates },
      'agent.roles.create': { ok: true, role: createdRole },
      'agent.sessions.create': { ok: true, session: { id: 'session-morning-guide' } },
    } });
    render(
      <MemoryRouter initialEntries={['/roles']}>
        <ControlTransportProvider transport={transport}>
          <TooltipProvider><RolesFeature /><LocationProbe /></TooltipProvider>
        </ControlTransportProvider>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: '创建角色' }));
    const name = screen.getByRole('textbox', { name: '角色名' });
    const tagline = screen.getByRole('textbox', { name: '角色一句话介绍' });
    const summary = screen.getByRole('textbox', { name: '角色说明' });
    expect(name).toHaveAttribute('maxlength', '40');
    expect(tagline).toHaveAttribute('maxlength', '80');
    expect(summary).toHaveAttribute('maxlength', '180');
    await user.type(name, '智鼬·晨光');
    await user.type(tagline, '先看清今天，再稳稳向前');
    await user.type(summary, '适合陪我整理早晨计划与关键证据。');
    expect(screen.getByText(/实际对话模型由 Agent 中的 Pi 模型目录选择/)).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: /构筑阶段/ }));
    const trait = screen.getByRole('textbox', { name: '新增表达特征' });
    await user.type(trait, '清晰{Enter}');
    await user.type(trait, '温和');
    await user.click(screen.getByRole('checkbox', { name: '协作主持' }));
    await user.click(screen.getByRole('button', { name: '创建角色' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.roles.create')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.roles.create')?.request.body).toEqual({
      displayName: '智鼬·晨光',
      tagline: '先看清今天，再稳稳向前',
      summary: '适合陪我整理早晨计划与关键证据。',
      traits: ['清晰', '温和'],
      timelineModel: 'sol',
      selectableModes: ['assistant', 'coordinator'],
    });
    expect(await screen.findByRole('button', { name: /智鼬·晨光/ })).toHaveAttribute('aria-current', 'true');
    expect(screen.getAllByText('构筑阶段')).not.toHaveLength(0);
    expect(screen.queryByText(/5\.6 (?:Luna|Terra|Sol)/)).not.toBeInTheDocument();
    expect(screen.getByText('清晰 · 温和')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '创建角色' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '开始对话' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/agent?session=session-morning-guide'));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.sessions.create')?.request.body).toEqual({
      title: '智鼬·晨光 对话',
      mode: 'assistant',
      roleId: 'morning-guide-v1',
      roleVersion: '1',
      workspaceRoots: [],
    });
  });

  it('keeps a role creation failure visible inside the dialog without losing the draft', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.subagents.templates': { ok: true, items: previewTemplates },
      'agent.roles.create': () => { throw new Error('角色名称已存在'); },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: '创建角色' }));
    await user.type(screen.getByRole('textbox', { name: '角色名' }), '智鼬·晨光');
    await user.type(screen.getByRole('textbox', { name: '角色一句话介绍' }), '先看清今天');
    await user.type(screen.getByRole('textbox', { name: '角色说明' }), '陪我整理今天的重点。');
    await user.type(screen.getByRole('textbox', { name: '新增表达特征' }), '清晰');
    await user.click(screen.getByRole('button', { name: '创建角色' }));

    const dialog = screen.getByRole('dialog', { name: '创建角色' });
    expect(await screen.findByRole('alert')).toHaveTextContent('角色名称已存在');
    expect(dialog).toContainElement(screen.getByRole('alert'));
    expect(screen.getByRole('textbox', { name: '角色名' })).toHaveValue('智鼬·晨光');
  });
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}
