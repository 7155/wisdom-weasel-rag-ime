import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
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
  it('keeps the partner page focused on identity instead of runtime task definitions', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);
    expect(await screen.findByText('此刻陪你输入，也陪你把事情想清楚')).toBeInTheDocument();
    expect(screen.getByText('适合交给她')).toBeInTheDocument();
    expect(screen.getByText('不建议交给她')).toBeInTheDocument();
    expect(screen.getAllByText('GPT-5.6 Sol').length).toBeGreaterThan(0);
    expect(screen.getAllByText('内置只读').length).toBeGreaterThan(0);
    expect(screen.getByText('默认')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '复制并自定义' })).toBeInTheDocument();
    expect(screen.queryByText('control-center-safe-v1')).not.toBeInTheDocument();
    expect(screen.queryByText('control-center-v1')).not.toBeInTheDocument();
    expect(screen.queryByText('任务助手')).not.toBeInTheDocument();
    expect(screen.queryByText('Room 岗位')).not.toBeInTheDocument();
    expect(screen.queryByText('协作规则')).not.toBeInTheDocument();
    await waitFor(() => expect(transport.requests.map((call) => call.request.pathId)).toEqual(expect.arrayContaining(['agent.roles.list', 'agent.role.models', 'agent.configuration.get'])));
    expect(transport.requests.some((call) => call.request.pathId === 'agent.subagents.templates')).toBe(false);
  });

  it('makes Room membership a capability while keeping task jobs dynamic', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect(await screen.findByText(/Room 成员、岗位和任务交接只在 Room 内管理/)).toBeInTheDocument();
    expect(screen.queryByText('协作配置')).not.toBeInTheDocument();
    expect(screen.queryByText('协作主持')).not.toBeInTheDocument();
    expect(screen.getByText('内置伙伴 · 只读')).toBeInTheDocument();
  });

  it('copies the selected built-in partner without changing her lifecycle phase', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: '复制并自定义' }));

    expect(screen.getByRole('dialog', { name: '添加伙伴' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /构筑阶段/ })).toBeChecked();
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
      roleId: 'companion-firstlight-v1',
      roleVersion: '1',
      workspaceRoots: [],
    });
  });

  it('reviews and activates selected Role Book proposals through an R1 preview', async () => {
    const user = userEvent.setup();
    const persona = previewPersonas[0]!;
    const roleBook = {
      ok: true,
      active: {
        revisionId: 'revision:1',
        revisionNumber: 1,
        status: 'active',
        sections: {
          personality: [],
          capabilities: [],
          recentWork: [{ text: '完成上下文重构' }],
          lessonsAndLimits: [],
          activeCommitments: [],
        },
      },
      history: [],
      dailyDrafts: [{
        draftId: 'role-book-draft:1',
        createdAtMs: 1_800_000_000_000,
        traitProposals: [{ text: '沟通时先给出具体例子', confidence: 0.9, sourceEvidenceIds: ['evidence:1'] }],
        capabilityProposals: [{ text: '能修复 SQLite 事务恢复问题', confidence: 0.95, sourceEvidenceIds: ['evidence:1'] }],
        lessonProposals: [{ text: '工具返回缺失字段时先验证边界契约', confidence: 0.88, sourceEvidenceIds: ['evidence:1'] }],
        commitmentProposals: [{ text: '下一轮发布前完成端到端回归', confidence: 0.92, sourceEvidenceIds: ['evidence:1'] }],
        decision: null,
      }],
    };
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: [persona] },
      'agent.subagents.templates': { ok: true, items: [] },
      'agent.roleBook.get': roleBook,
      'agent.roleBook.activation.preview': {
        ok: true,
        previewToken: 'preview-role-book',
        payloadSha256: 'sha256:role-book',
        summary: {
          risk: 'R1',
          evidenceCount: 1,
          items: ['采用 1 条协作特征', '采用 1 条能力证据'],
          diff: {
            sections: [{
              section: 'personality',
              label: '协作特征',
              added: [{ itemId: 'trait:1', text: '沟通时先给出具体例子', evidenceIds: ['evidence:1'] }],
              removed: [],
              changed: [],
            }],
          },
        },
      },
      'agent.roleBook.activation.apply': {
        ok: true,
        receiptId: 'receipt-role-book',
        rollbackAvailable: true,
        rollbackToken: 'rollback-role-book',
        payloadSha256: 'sha256:role-book',
        result: { revision: { revisionId: 'revision:2', status: 'active' } },
      },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    await screen.findByText(persona.tagline);
    await user.click(screen.getByRole('button', { name: '角色记忆与成长档案' }));
    const lesson = await screen.findByRole('checkbox', { name: /工具返回缺失字段时先验证边界契约/ });
    const previewButton = screen.getByRole('button', { name: '预览启用' });
    expect(previewButton).toBeDisabled();
    expect(screen.getByRole('group', { name: '经验与边界' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '当前承诺' })).toBeInTheDocument();
    await user.click(lesson);
    expect(previewButton).toBeEnabled();
    await user.click(lesson);
    expect(previewButton).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /沟通时先给出具体例子/ }));
    await user.click(screen.getByRole('checkbox', { name: /能修复 SQLite 事务恢复问题/ }));
    await user.click(lesson);
    await user.click(screen.getByRole('checkbox', { name: /下一轮发布前完成端到端回归/ }));
    await user.click(previewButton);

    const dialog = await screen.findByRole('dialog', { name: '启用成长档案修订' });
    expect(dialog).toHaveTextContent('R1 确认');
    expect(dialog).toHaveTextContent('采用 1 条能力证据');
    expect(dialog).toHaveTextContent('沟通时先给出具体例子');
    expect(dialog).toHaveTextContent('已核验 1 条证据');
    await user.click(screen.getByRole('button', { name: '确认启用' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.roleBook.activation.apply')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.roleBook.activation.preview')?.request.body).toEqual({
      roleId: persona.roleId,
      roleVersion: persona.version,
      revisionId: '',
      draftId: 'role-book-draft:1',
      traitIndexes: [0],
      capabilityIndexes: [0],
      lessonIndexes: [0],
      commitmentIndexes: [0],
    });
    expect(transport.requests.find((call) => call.request.pathId === 'agent.roleBook.activation.apply')?.request.body).toMatchObject({
      traitIndexes: [0],
      capabilityIndexes: [0],
      lessonIndexes: [0],
      commitmentIndexes: [0],
      previewToken: 'preview-role-book',
      payloadSha256: 'sha256:role-book',
      confirmText: 'apply',
    });
    expect(await screen.findByRole('button', { name: '撤销本次启用' })).toBeInTheDocument();
  });

  it('shows builtin model and thinking as a fixed runtime profile', async () => {
    const configured = {
      ...previewPersonas[0]!,
      defaults: {
        ...previewPersonas[0]!.defaults,
        modelProfile: 'gpt/gpt-5.6-sol',
        thinkingLevel: 'max' as const,
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
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect((await screen.findAllByText('GPT-5.6 Sol')).length).toBeGreaterThan(0);
    expect(screen.getByText('内置模型')).toBeInTheDocument();
    expect(screen.getByText('Max')).toBeInTheDocument();
    expect(screen.queryByLabelText('角色默认模型')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '保存默认设置' })).not.toBeInTheDocument();
  });

  it('exposes Flash as a selectable fast-scan role with explicit boundaries', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.subagents.templates': { ok: true, items: previewTemplates },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: /智鼬·闪念/ }));
    expect(screen.getAllByText('DeepSeek V4 Flash').length).toBeGreaterThan(0);
    expect(screen.getByText('超长材料高速扫读与提取')).toBeInTheDocument();
    expect(screen.getByText('归类、去重和格式转换')).toBeInTheDocument();
    expect(screen.getByText('复杂推理')).toBeInTheDocument();
    expect(screen.getByText('最终验收')).toBeInTheDocument();
    expect(screen.getByText('不启用推理')).toBeInTheDocument();
  });

  it('does not substitute preview Personas when the native catalog is empty', async () => {
    const transport = new StubControlTransport('native', {
      'agent.roles.list': { ok: true, items: [] },
      'agent.subagents.templates': { ok: true, items: [] },
    });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect(await screen.findByText('本机还没有可用伙伴。')).toBeInTheDocument();
    expect(screen.queryByText('此刻陪你输入，也陪你把事情想清楚')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '开始对话' })).not.toBeInTheDocument();
  });

  it('does not make the partner catalog depend on task-template availability', async () => {
    const user = userEvent.setup();
    const transport = new StubControlTransport('native', {
      'agent.roles.list': { ok: true, items: previewPersonas },
    });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect(await screen.findByText('此刻陪你输入，也陪你把事情想清楚')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始对话' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: /智鼬·初识/ }));
    expect(transport.requests.map((request) => request.pathId)).toEqual([
      'agent.roles.list',
      'agent.role.models',
      'agent.configuration.get',
    ]);
  });

  it('makes a role catalog failure visible without inventing fallback partners', async () => {
    const transport = new StubControlTransport('native', {
      'agent.roles.list': () => { throw new Error('role service unavailable'); },
    });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect(await screen.findByRole('status')).toHaveTextContent('角色目录：暂时无法读取，请稍后重试。');
    expect(screen.queryByRole('button', { name: '开始对话' })).not.toBeInTheDocument();
    expect(screen.getByText('本机还没有可用伙伴。')).toBeInTheDocument();
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
      visualProfile: previewPersonas[0]!.visualProfile,
      selectableModes: ['assistant', 'coordinator'] as ['assistant', 'coordinator'],
      runtimeCharacteristics: {
        ...previewPersonas[2]!.runtimeCharacteristics,
        suitableTasks: ['整理早晨计划', '核对关键证据'] as ['整理早晨计划', '核对关键证据'],
        unsuitableTasks: ['替用户做高风险决定'] as ['替用户做高风险决定'],
      },
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

    await user.click(await screen.findByRole('button', { name: '添加伙伴' }));
    const name = screen.getByRole('textbox', { name: '角色名' });
    const tagline = screen.getByRole('textbox', { name: '角色一句话介绍' });
    const summary = screen.getByRole('textbox', { name: '角色说明' });
    const suitableTasks = screen.getByRole('textbox', { name: '适合任务' });
    const unsuitableTasks = screen.getByRole('textbox', { name: '不建议任务' });
    expect(name).toHaveAttribute('maxlength', '40');
    expect(tagline).toHaveAttribute('maxlength', '80');
    expect(summary).toHaveAttribute('maxlength', '180');
    await user.type(name, '智鼬·晨光');
    await user.type(tagline, '先看清今天，再稳稳向前');
    await user.type(summary, '适合陪我整理早晨计划与关键证据。');
    await user.type(suitableTasks, '整理早晨计划{Enter}核对关键证据');
    await user.type(unsuitableTasks, '替用户做高风险决定');
    expect(screen.getByText(/模型和工具在运行设置中独立管理/)).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: /构筑阶段/ }));
    const trait = screen.getByRole('textbox', { name: '新增表达特征' });
    await user.type(trait, '清晰{Enter}');
    await user.type(trait, '温和');
    await user.click(screen.getByRole('checkbox', { name: '允许加入 Room' }));
    await user.click(screen.getByRole('button', { name: '添加伙伴' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.roles.create')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.roles.create')?.request.body).toEqual({
      displayName: '智鼬·晨光',
      tagline: '先看清今天，再稳稳向前',
      summary: '适合陪我整理早晨计划与关键证据。',
      traits: ['清晰', '温和'],
      timelineModel: 'sol',
      selectableModes: ['assistant', 'coordinator'],
      suitableTasks: ['整理早晨计划', '核对关键证据'],
      unsuitableTasks: ['替用户做高风险决定'],
    });
    expect(await screen.findByRole('button', { name: /智鼬·晨光/ })).toHaveAttribute('aria-current', 'true');
    expect(screen.getAllByText('构筑阶段')).not.toHaveLength(0);
    expect(screen.getAllByText('我的伙伴').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '编辑伙伴' })).toBeInTheDocument();
    expect(screen.getAllByText('智鼬·晨光').length).toBeGreaterThan(0);
    expect(screen.queryByRole('dialog', { name: '添加伙伴' })).not.toBeInTheDocument();

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

  it('edits a user-owned companion while builtin companions stay read-only', async () => {
    const user = userEvent.setup();
    const customRole = {
      ...previewPersonas[2]!,
      roleId: 'persona-rain-v1',
      displayName: '智鼬·雨天',
      tagline: '陪你安静整理',
      summary: '偏向温和复盘。',
      traits: ['温和'] as ['温和'],
      defaults: { ...previewPersonas[2]!.defaults, modelPolicy: 'session-selected' },
      selectableModes: ['assistant'] as ['assistant'],
      runtimeCharacteristics: {
        ...previewPersonas[2]!.runtimeCharacteristics,
        suitableTasks: ['温和复盘'] as ['温和复盘'],
        unsuitableTasks: ['替用户做高风险决定'] as ['替用户做高风险决定'],
      },
    };
    const updatedRole = {
      ...customRole,
      displayName: '智鼬·暮雨',
      tagline: '先安静看清，再一起往前',
      summary: '偏向温和复盘与明确下一步。',
      traits: ['温和', '清楚'] as ['温和', '清楚'],
      selectableModes: ['assistant', 'coordinator'] as ['assistant', 'coordinator'],
      runtimeCharacteristics: {
        ...customRole.runtimeCharacteristics,
        suitableTasks: ['温和复盘', '明确下一步'] as ['温和复盘', '明确下一步'],
        unsuitableTasks: ['未经证据的个人判断'] as ['未经证据的个人判断'],
      },
    };
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: [previewPersonas[0], customRole] },
      'agent.subagents.templates': { ok: true, items: [] },
      'agent.roles.update': { ok: true, role: updatedRole },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect(await screen.findByRole('button', { name: '复制并自定义' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '编辑伙伴' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /智鼬·雨天/ }));
    await user.click(screen.getByRole('button', { name: '编辑伙伴' }));
    expect(screen.getByRole('dialog', { name: '编辑伙伴' })).toHaveTextContent('工具与安全边界仍由系统管理');
    await user.clear(screen.getByRole('textbox', { name: '角色名' }));
    await user.type(screen.getByRole('textbox', { name: '角色名' }), '智鼬·暮雨');
    await user.clear(screen.getByRole('textbox', { name: '角色一句话介绍' }));
    await user.type(screen.getByRole('textbox', { name: '角色一句话介绍' }), '先安静看清，再一起往前');
    await user.clear(screen.getByRole('textbox', { name: '角色说明' }));
    await user.type(screen.getByRole('textbox', { name: '角色说明' }), '偏向温和复盘与明确下一步。');
    await user.clear(screen.getByRole('textbox', { name: '适合任务' }));
    await user.type(screen.getByRole('textbox', { name: '适合任务' }), '温和复盘{Enter}明确下一步');
    await user.clear(screen.getByRole('textbox', { name: '不建议任务' }));
    await user.type(screen.getByRole('textbox', { name: '不建议任务' }), '未经证据的个人判断');
    await user.type(screen.getByRole('textbox', { name: '新增表达特征' }), '清楚{Enter}');
    await user.click(screen.getByRole('checkbox', { name: '允许加入 Room' }));
    await user.click(screen.getByRole('button', { name: '保存伙伴' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.roles.update')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.roles.update')?.request.body).toEqual({
      roleId: customRole.roleId,
      roleVersion: customRole.version,
      displayName: '智鼬·暮雨',
      tagline: '先安静看清，再一起往前',
      summary: '偏向温和复盘与明确下一步。',
      traits: ['温和', '清楚'],
      timelineModel: 'luna',
      selectableModes: ['assistant', 'coordinator'],
      suitableTasks: ['温和复盘', '明确下一步'],
      unsuitableTasks: ['未经证据的个人判断'],
    });
    expect(await screen.findByRole('button', { name: /智鼬·暮雨/ })).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('button', { name: '编辑伙伴' })).toBeInTheDocument();
  });

  it('sets a real default companion and protects it from accidental removal', async () => {
    const user = userEvent.setup();
    const customRole = {
      ...previewPersonas[2]!,
      roleId: 'persona-default-v1',
      displayName: '智鼬·灯塔',
      tagline: '每次新对话都先帮你找到方向',
      defaults: { ...previewPersonas[2]!.defaults, modelPolicy: 'session-selected' },
    };
    const configuration = (revision: number, roleId: string) => ({
      ok: true,
      configuration: {
        revision,
        configuration: {
          sessionDefaults: { roleId, roleVersion: '1' },
        },
      },
    });
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: [previewPersonas[0], customRole] },
      'agent.subagents.templates': { ok: true, items: [] },
      'agent.configuration.get': configuration(7, previewPersonas[0]!.roleId),
      'agent.configuration.update': configuration(8, customRole.roleId),
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: /智鼬·灯塔/ }));
    await user.click(screen.getByRole('button', { name: '设为默认' }));

    await waitFor(() => expect(screen.getByText('新对话默认伙伴')).toBeInTheDocument());
    expect(transport.requests.find((call) => call.request.pathId === 'agent.configuration.update')?.request.body).toEqual({
      expectedRevision: 7,
      changes: {
        'sessionDefaults.roleId': customRole.roleId,
        'sessionDefaults.roleVersion': customRole.version,
      },
      updatedBy: 'roles-ui',
    });
    expect(screen.getByRole('button', { name: '移除伙伴' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '移除伙伴' })).toHaveAttribute('title', '请先选择另一位默认伙伴');
  });

  it('removes a user companion from new selection without implying old conversations are deleted', async () => {
    const user = userEvent.setup();
    const customRole = {
      ...previewPersonas[2]!,
      roleId: 'persona-archive-v1',
      displayName: '智鼬·旧页',
      tagline: '陪你整理已经完成的章节',
      defaults: { ...previewPersonas[2]!.defaults, modelPolicy: 'session-selected' },
    };
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: [previewPersonas[0], customRole] },
      'agent.subagents.templates': { ok: true, items: [] },
      'agent.configuration.get': {
        ok: true,
        configuration: {
          revision: 3,
          configuration: {
            sessionDefaults: { roleId: previewPersonas[0]!.roleId, roleVersion: '1' },
          },
        },
      },
      'agent.roles.archive': { ok: true, roleId: customRole.roleId, roleVersion: customRole.version },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: /智鼬·旧页/ }));
    await user.click(screen.getByRole('button', { name: '移除伙伴' }));
    const dialog = screen.getByRole('dialog', { name: '移除这个伙伴？' });
    expect(dialog).toHaveTextContent('已有对话仍保留并可继续');
    await user.click(within(dialog).getByRole('button', { name: '移除伙伴' }));

    await waitFor(() => expect(screen.queryByRole('button', { name: /智鼬·旧页/ })).not.toBeInTheDocument());
    expect(transport.requests.find((call) => call.request.pathId === 'agent.roles.archive')?.request.body).toEqual({
      roleId: customRole.roleId,
      roleVersion: customRole.version,
    });
    expect(screen.getByRole('status')).toHaveTextContent('已有对话仍可继续');
  });

  it('keeps a role creation failure visible inside the dialog without losing the draft', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.subagents.templates': { ok: true, items: previewTemplates },
      'agent.roles.create': () => { throw new Error('角色名称已存在'); },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: '添加伙伴' }));
    await user.type(screen.getByRole('textbox', { name: '角色名' }), '智鼬·晨光');
    await user.type(screen.getByRole('textbox', { name: '角色一句话介绍' }), '先看清今天');
    await user.type(screen.getByRole('textbox', { name: '角色说明' }), '陪我整理今天的重点。');
    await user.type(screen.getByRole('textbox', { name: '适合任务' }), '整理今天重点');
    await user.type(screen.getByRole('textbox', { name: '不建议任务' }), '高风险独立决定');
    await user.type(screen.getByRole('textbox', { name: '新增表达特征' }), '清晰');
    await user.click(screen.getByRole('button', { name: '添加伙伴' }));

    const dialog = screen.getByRole('dialog', { name: '添加伙伴' });
    expect(await screen.findByRole('alert')).toHaveTextContent('角色名称已存在');
    expect(dialog).toContainElement(screen.getByRole('alert'));
    expect(screen.getByRole('textbox', { name: '角色名' })).toHaveValue('智鼬·晨光');
  });
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}
