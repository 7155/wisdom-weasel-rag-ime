import {
  Bot,
  BookOpen,
  BrainCircuit,
  Check,
  Cpu,
  MessageCirclePlus,
  MessagesSquare,
  Network,
  Plug,
  Plus,
  RotateCcw,
  ShieldCheck,
  Save,
  Sparkles,
  Star,
  Trash2,
  UserRoundPlus,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  IconButton,
  Select,
} from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { AgentModelCatalogV1 } from '@/contracts/generated/agent-model-catalog.v1';
import { previewPersonas } from '@/features/agent/preview-data';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { roleItems } from '@/features/agent/types';
import { publicErrorText } from '@/features/overview/management-ui';
import {
  arrayValue,
  agentDefaultCompanion,
  agentModelRouting,
  createdSessionId,
  ensureControlOk,
  normalizeTrait,
  normalizedTraits,
  numberValue,
  personaExpressionTraits,
  personaPhase,
  record,
  roleBookDailyDrafts,
  roleBookHistory,
  roleModelCatalog,
  textValue,
  thinkingLabel,
  timelineOptions,
  toggleIndex,
  type AgentDefaultCompanion,
  type AgentModelRouting,
  type RoleBookActivationSelection,
  type RoleBookDailyDraft,
  type RoleBookProposal,
  type RoleModelCatalog,
  type TimelineModel,
} from './role-model';
import './roles.css';

type CatalogLoadState = 'loading' | 'ready' | 'error';

export function RolesFeature() {
  const transport = useControlTransport();
  const navigate = useNavigate();
  const createReturnFocusRef = useRef<HTMLElement | null>(null);
  const [view, setView] = useState<'companions' | 'growth'>('companions');
  const [personas, setPersonas] = useState<AgentPersonaV1[]>(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas : []);
  const [modelCatalog, setModelCatalog] = useState<RoleModelCatalog>({ providers: [] });
  const [modelRouting, setModelRouting] = useState<AgentModelRouting | null>(null);
  const [routingDraft, setRoutingDraft] = useState<AgentModelRouting | null>(null);
  const [routingSaving, setRoutingSaving] = useState(false);
  const [pluginSummary, setPluginSummary] = useState({ tools: 0, extensions: 0, available: false });
  const [selectedPersona, setSelectedPersona] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas[0]?.roleId ?? '' : '');
  const [sessionCreating, setSessionCreating] = useState(false);
  const [roleCreating, setRoleCreating] = useState(false);
  const [defaultSaving, setDefaultSaving] = useState(false);
  const [roleArchiving, setRoleArchiving] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createDisplayName, setCreateDisplayName] = useState('');
  const [createTagline, setCreateTagline] = useState('');
  const [createSummary, setCreateSummary] = useState('');
  const [createTraits, setCreateTraits] = useState<string[]>([]);
  const [createSuitableTasks, setCreateSuitableTasks] = useState('');
  const [createUnsuitableTasks, setCreateUnsuitableTasks] = useState('');
  const [traitDraft, setTraitDraft] = useState('');
  const [timelineModel, setTimelineModel] = useState<TimelineModel>('terra');
  const [roomEnabled, setRoomEnabled] = useState(false);
  const [catalogReload, setCatalogReload] = useState(0);
  const [roleCatalogState, setRoleCatalogState] = useState<CatalogLoadState>(() => (
    __CONTROL_PREVIEW__ && transport.kind === 'mock' ? 'ready' : 'loading'
  ));
  const [catalogNotice, setCatalogNotice] = useState('');
  const [actionNotice, setActionNotice] = useState('');
  const [createError, setCreateError] = useState('');
  const [editingPersona, setEditingPersona] = useState<AgentPersonaV1 | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<AgentPersonaV1 | null>(null);
  const [archiveError, setArchiveError] = useState('');
  const [defaultCompanion, setDefaultCompanion] = useState<AgentDefaultCompanion | null>(() => {
    if (!(__CONTROL_PREVIEW__ && transport.kind === 'mock')) return null;
    const initial = previewPersonas.find((item) => item.runtimeCharacteristics.isDefault);
    return initial ? { revision: 0, roleId: initial.roleId, roleVersion: initial.version } : null;
  });
  useEffect(() => {
    let active = true;
    setRoleCatalogState('loading');
    setCatalogNotice('');
    void Promise.allSettled([
      transport.request({ pathId: 'agent.roles.list' }),
      transport.request({ pathId: 'agent.role.models' }),
      transport.request({ pathId: 'agent.configuration.get' }),
      transport.request({ pathId: 'agent.tools.list' }),
      transport.request({ pathId: 'agent.extensions.list' }),
    ]).then(([roleResult, modelResult, configurationResult, toolsResult, extensionsResult]) => {
      if (!active) return;
      const errors: string[] = [];
      if (roleResult.status === 'fulfilled') {
        const roles = roleItems(roleResult.value);
        setRoleCatalogState('ready');
        if (roles.length || !(__CONTROL_PREVIEW__ && transport.kind === 'mock')) {
          setPersonas(roles);
          setSelectedPersona((current) => roles.some((item) => item.roleId === current) ? current : roles[0]?.roleId ?? '');
        }
      } else {
        setRoleCatalogState('error');
        errors.push('伙伴目录暂时无法读取。');
      }
      if (modelResult.status === 'fulfilled') {
        setModelCatalog(roleModelCatalog(modelResult.value));
      } else {
        errors.push('模型目录暂时未读取，运行路由可能不完整。');
      }
      if (configurationResult.status === 'fulfilled') {
        setDefaultCompanion(agentDefaultCompanion(configurationResult.value));
        const routing = agentModelRouting(configurationResult.value);
        setModelRouting(routing);
        setRoutingDraft(routing);
        if (!routing) errors.push('模型运行路由版本未知，当前设置不会被猜测。');
      } else {
        errors.push('模型路由与默认身份暂时未读取。');
      }
      setPluginSummary({
        tools: toolsResult.status === 'fulfilled' ? arrayValue(record(toolsResult.value).items).length : 0,
        extensions: extensionsResult.status === 'fulfilled' ? arrayValue(record(extensionsResult.value).items).length : 0,
        available: toolsResult.status === 'fulfilled' || extensionsResult.status === 'fulfilled',
      });
      setCatalogNotice(errors.join(' '));
    });
    return () => { active = false; };
  }, [catalogReload, transport]);
  const persona = personas.find((item) => item.roleId === selectedPersona);
  const personaIsDefault = Boolean(persona && defaultCompanion
    && persona.roleId === defaultCompanion.roleId
    && persona.version === defaultCompanion.roleVersion);

  async function saveModelRouting(): Promise<void> {
    if (!modelRouting || !routingDraft || routingSaving) return;
    setRoutingSaving(true);
    setActionNotice('');
    try {
      const response = await transport.request({
        pathId: 'agent.configuration.update',
        body: {
          expectedRevision: modelRouting.revision,
          changes: {
            'modelRouting.sessionModelProfile': routingDraft.sessionModelProfile,
            'modelRouting.sessionThinkingLevel': routingDraft.sessionThinkingLevel,
            'modelRouting.roomPartnerModelProfile': routingDraft.roomPartnerModelProfile,
            'modelRouting.roomPartnerThinkingLevel': routingDraft.roomPartnerThinkingLevel,
            'modelRouting.toolAgentModelProfile': routingDraft.toolAgentModelProfile,
            'modelRouting.toolAgentThinkingLevel': routingDraft.toolAgentThinkingLevel,
          },
          updatedBy: 'model-routing-ui',
        },
      });
      const updated = agentModelRouting(response);
      if (!updated) throw new Error('模型路由保存结果无法确认，请刷新后重试。');
      setModelRouting(updated);
      setRoutingDraft(updated);
      setDefaultCompanion(agentDefaultCompanion(response));
      setActionNotice('普通对话、Room Partner 与 Tool Agent 的默认模型已保存；现有运行不会被中途切换。');
    } catch (error) {
      setActionNotice(publicErrorText(error, '模型运行路由暂时无法保存。'));
    } finally {
      setRoutingSaving(false);
    }
  }

  async function startPersonaSession(): Promise<void> {
    if (!persona || sessionCreating) return;
    setSessionCreating(true);
    setActionNotice('');
    try {
      const response = await transport.request({
        pathId: 'agent.sessions.create',
        body: {
          title: `${persona.displayName} 对话`,
          mode: 'assistant',
          roleId: persona.roleId,
          roleVersion: persona.version,
          workspaceRoots: [],
        },
      });
      const sessionId = createdSessionId(response);
      if (!sessionId) throw new Error('对话暂时无法创建，请重试。');
      navigate(`/agent?session=${encodeURIComponent(sessionId)}`);
    } catch (error) {
      setActionNotice(publicErrorText(error));
    } finally {
      setSessionCreating(false);
    }
  }

  function captureCreateReturnFocus(): void {
    createReturnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
  }

  function beginRoleCreation(): void {
    captureCreateReturnFocus();
    setCreateDisplayName('');
    setCreateTagline('');
    setCreateSummary('');
    setCreateTraits([]);
    setCreateSuitableTasks('');
    setCreateUnsuitableTasks('');
    setTraitDraft('');
    setTimelineModel('terra');
    setRoomEnabled(false);
    setActionNotice('');
    setCreateError('');
    setEditingPersona(null);
    setCreateOpen(true);
  }

  function beginRoleEdit(target: AgentPersonaV1): void {
    captureCreateReturnFocus();
    const phase = personaPhase(target).id;
    setCreateDisplayName(target.displayName);
    setCreateTagline(target.tagline);
    setCreateSummary(target.summary);
    setCreateTraits([...personaExpressionTraits(target)]);
    setCreateSuitableTasks(target.runtimeCharacteristics.suitableTasks.join('\n'));
    setCreateUnsuitableTasks(target.runtimeCharacteristics.unsuitableTasks.join('\n'));
    setTraitDraft('');
    setTimelineModel(phase === 'luna' || phase === 'terra' || phase === 'sol'
      ? phase
      : 'terra');
    setRoomEnabled(target.selectableModes.includes('coordinator'));
    setActionNotice('');
    setCreateError('');
    setEditingPersona(target);
    setCreateOpen(true);
  }

  function beginRoleCopy(target: AgentPersonaV1): void {
    const phase = personaPhase(target).id;
    beginRoleCreation();
    setCreateDisplayName(`${target.displayName}·自定义`);
    setCreateTagline(target.tagline);
    setCreateSummary(target.summary);
    setCreateTraits([...personaExpressionTraits(target)]);
    setCreateSuitableTasks(target.runtimeCharacteristics.suitableTasks.join('\n'));
    setCreateUnsuitableTasks(target.runtimeCharacteristics.unsuitableTasks.join('\n'));
    setTimelineModel(phase === 'luna' || phase === 'terra' || phase === 'sol'
      ? phase
      : 'terra');
    setRoomEnabled(target.selectableModes.includes('coordinator'));
  }

  function addTrait(): void {
    const value = normalizeTrait(traitDraft);
    if (!value || createTraits.some((trait) => trait.toLocaleLowerCase() === value.toLocaleLowerCase())) {
      setTraitDraft('');
      return;
    }
    if (createTraits.length >= 5) return;
    setCreateTraits((current) => [...current, value]);
    setTraitDraft('');
  }

  async function createRole(): Promise<void> {
    if (roleCreating) return;
    const traits = normalizedTraits(createTraits, traitDraft);
    const displayName = createDisplayName.trim();
    const tagline = createTagline.trim();
    const summary = createSummary.trim();
    const suitableTasks = taskBoundaryItems(createSuitableTasks);
    const unsuitableTasks = taskBoundaryItems(createUnsuitableTasks);
    if (!displayName || !tagline || !summary || !traits.length
      || !taskBoundariesValid(createSuitableTasks)
      || !taskBoundariesValid(createUnsuitableTasks)) return;
    setRoleCreating(true);
    setCreateError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: editingPersona ? 'agent.roles.update' : 'agent.roles.create',
        body: {
          ...(editingPersona ? { roleId: editingPersona.roleId, roleVersion: editingPersona.version } : {}),
          displayName,
          tagline,
          summary,
          traits,
          timelineModel,
          selectableModes: roomEnabled
            ? ['assistant', 'coordinator']
            : ['assistant'],
          suitableTasks,
          unsuitableTasks,
        },
      });
      const [created] = roleItems({ items: [record(response).role] });
      if (!created) throw new Error('新伙伴的保存结果暂时无法确认，请刷新后重试。');
      setPersonas((current) => [
        created,
        ...current.filter((item) => item.roleId !== created.roleId || item.version !== created.version),
      ]);
      setSelectedPersona(created.roleId);
      setCreateOpen(false);
      setEditingPersona(null);
    } catch (error) {
      setCreateError(publicErrorText(error, '角色暂时无法创建，请稍后重试。'));
    } finally {
      setRoleCreating(false);
    }
  }

  async function makeDefaultCompanion(): Promise<void> {
    if (!persona || !defaultCompanion || defaultCompanion.revision <= 0 || defaultSaving || personaIsDefault) return;
    setDefaultSaving(true);
    setActionNotice('');
    try {
      const response = await transport.request({
        pathId: 'agent.configuration.update',
        body: {
          expectedRevision: defaultCompanion.revision,
          changes: {
            'sessionDefaults.roleId': persona.roleId,
            'sessionDefaults.roleVersion': persona.version,
          },
          updatedBy: 'roles-ui',
        },
      });
      const updated = agentDefaultCompanion(response);
      if (!updated) throw new Error('默认伙伴的保存结果暂时无法确认，请刷新后重试。');
      setDefaultCompanion(updated);
      setActionNotice(`${persona.displayName} 已设为新对话的默认伙伴。`);
    } catch (error) {
      setActionNotice(publicErrorText(error, '默认伙伴暂时无法保存。'));
    } finally {
      setDefaultSaving(false);
    }
  }

  async function archiveCompanion(): Promise<void> {
    if (!archiveTarget || roleArchiving) return;
    const target = archiveTarget;
    setRoleArchiving(true);
    setArchiveError('');
    try {
      await transport.request({
        pathId: 'agent.roles.archive',
        body: { roleId: target.roleId, roleVersion: target.version },
      });
      const remaining = personas.filter((item) => (
        item.roleId !== target.roleId || item.version !== target.version
      ));
      setPersonas(remaining);
      setSelectedPersona((current) => current === target.roleId
        ? remaining.find((item) => item.roleId === defaultCompanion?.roleId)?.roleId ?? remaining[0]?.roleId ?? ''
        : current);
      setActionNotice(`${target.displayName} 已从伙伴目录移除；已有对话仍可继续。`);
      setArchiveTarget(null);
    } catch (error) {
      setArchiveError(publicErrorText(error, '伙伴暂时无法移除。'));
    } finally {
      setRoleArchiving(false);
    }
  }

  const pendingTraits = normalizedTraits(createTraits, traitDraft);

  return <>
    <main className="roles-feature" data-route-id="roles">
      <header className="roles-header"><span><h1>模型与插件</h1><p>按运行职责选择默认模型；伙伴身份不再决定算力，插件仍保持独立安装与授权。</p></span></header>
      {actionNotice ? <p className="roles-notice" role="status">{actionNotice}</p> : null}
      {catalogNotice && (personas.length > 0 || roleCatalogState !== 'error') ? <div className="roles-catalog-notice">
        <span><strong>部分运行信息没有读完</strong><small>{catalogNotice}</small></span>
        <Button variant="quiet" size="small" leadingIcon={<RotateCcw size={14} />} onClick={() => setCatalogReload((current) => current + 1)}>重新读取页面信息</Button>
      </div> : null}
      <ModelRoutingPanel
        catalog={modelCatalog}
        draft={routingDraft}
        saved={modelRouting}
        saving={routingSaving}
        onChange={setRoutingDraft}
        onOpenProviders={() => navigate('/configuration')}
        onSave={() => void saveModelRouting()}
      />
      <section className="model-plugin-overview" aria-labelledby="plugin-overview-title">
        <span className="model-plugin-overview__icon"><Plug size={20} /></span>
        <span><h2 id="plugin-overview-title">插件与工具</h2><p>扩展为 Session、Room 和 Tool Agent 提供能力；模型路由不会绕过插件权限与确认。</p></span>
        <dl><div><dt>可用工具</dt><dd>{pluginSummary.available ? pluginSummary.tools : '—'}</dd></div><div><dt>已安装插件</dt><dd>{pluginSummary.available ? pluginSummary.extensions : '—'}</dd></div></dl>
        <Button variant="quiet" size="small" leadingIcon={<Plug size={14} />} onClick={() => navigate('/plugins')}>管理插件</Button>
      </section>
      <section className="roles-legacy-section" aria-labelledby="legacy-companion-title">
        <header><span><h2 id="legacy-companion-title">兼容伙伴身份</h2><p>这里只保留称呼、表达方式和长期成长；新运行使用上方按职责配置的模型。</p></span>{view === 'companions' ? <Button variant="quiet" size="small" leadingIcon={<UserRoundPlus size={15} />} onClick={beginRoleCreation}>添加伙伴</Button> : null}</header>
        <div className="roles-layout">
          <section className="persona-grid" aria-label="伙伴目录">{personas.length ? personas.map((item) => { const builtin = item.defaults.modelPolicy === 'fixed'; const isDefault = item.roleId === defaultCompanion?.roleId && item.version === defaultCompanion.roleVersion; return <button type="button" key={`${item.roleId}:${item.version}`} data-accent={item.visualProfile.accentToken} aria-current={item.roleId === selectedPersona} onClick={() => { setSelectedPersona(item.roleId); setActionNotice(''); }}><PersonaAvatar persona={item} size="large" /><span className="persona-grid__copy"><strong>{item.displayName}</strong><small>{item.tagline}</small></span><div className="persona-grid__badges"><i className="persona-grid__kind" data-kind={builtin ? 'builtin' : 'custom'}>{builtin ? '内置伙伴' : '我的伙伴'}</i>{isDefault ? <em className="persona-grid__default">默认</em> : null}</div></button>; }) : roleCatalogState === 'loading' ? <div className="roles-catalog-state" aria-live="polite" aria-busy="true"><span className="roles-catalog-spinner" aria-hidden="true" /><span><strong>正在读取伙伴</strong><small>很快就会显示本机已有的伙伴。</small></span></div> : roleCatalogState === 'error' ? <div className="roles-catalog-state roles-catalog-state--error" role="alert"><span><strong>伙伴目录没有打开</strong><small>本机服务暂时没有返回伙伴信息。重新读取不会更改已有伙伴。</small></span><Button variant="quiet" size="small" leadingIcon={<RotateCcw size={14} />} onClick={() => setCatalogReload((current) => current + 1)}>重新读取伙伴</Button></div> : <div className="roles-catalog-state"><span><strong>还没有伙伴</strong><small>添加后，可以为不同类型的工作选择更合适的陪伴方式。</small></span></div>}</section>
          {persona && view === 'companions' ? <PersonaInspector canChangeDefault={Boolean(defaultCompanion && defaultCompanion.revision > 0)} defaulted={personaIsDefault} defaultSaving={defaultSaving} persona={persona} onOpenGrowth={() => setView('growth')} onEdit={() => beginRoleEdit(persona)} onCopy={() => beginRoleCopy(persona)} onSetDefault={() => void makeDefaultCompanion()} onArchive={() => { setArchiveError(''); setArchiveTarget(persona); }} onStart={() => void startPersonaSession()} starting={sessionCreating} /> : null}
          {persona && view === 'growth' ? <PersonaGrowthInspector persona={persona} onBack={() => setView('companions')} /> : null}
        </div>
      </section>
    </main>
    <Dialog open={createOpen} onOpenChange={(open) => { if (!roleCreating) { setCreateOpen(open); if (!open) setCreateError(''); } }}>
      <DialogContent
        className="role-create-dialog"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          createReturnFocusRef.current?.focus();
        }}
      >
        <DialogHeader><DialogTitle>{editingPersona ? '编辑伙伴' : '添加伙伴'}</DialogTitle><DialogDescription>{editingPersona ? '调整她之后的称呼、表达方式和相处阶段；工具与安全边界仍由系统管理。' : '从内置伙伴出发，或创建一位更贴近你的长期伙伴。模型和工具在运行设置中独立管理。'}</DialogDescription></DialogHeader>
        <form id="role-create-form" className="role-create-form" onSubmit={(event) => { event.preventDefault(); void createRole(); }}>
          {createError ? <p className="role-create-error" role="alert">{createError}</p> : null}
          <div className="role-create-two-columns">
            <label className="role-create-field"><span>伙伴名字</span><input autoFocus maxLength={40} value={createDisplayName} onChange={(event) => setCreateDisplayName(event.target.value)} placeholder="例如：晨光" aria-label="伙伴名字" /></label>
            <label className="role-create-field"><span>一句话介绍</span><input maxLength={80} value={createTagline} onChange={(event) => setCreateTagline(event.target.value)} placeholder="她会怎样陪你" aria-label="角色一句话介绍" /></label>
          </div>
          <label className="role-create-field"><span>她能怎样陪你</span><textarea rows={3} maxLength={180} value={createSummary} onChange={(event) => setCreateSummary(event.target.value)} placeholder="她更适合陪你完成哪些事情" aria-label="伙伴说明" /></label>
          <div className="role-create-two-columns role-create-boundaries">
            <label className="role-create-field"><span>适合任务 <small>{taskBoundaryItems(createSuitableTasks).length}/4，每行一项</small></span><textarea rows={4} maxLength={324} value={createSuitableTasks} onChange={(event) => setCreateSuitableTasks(event.target.value)} placeholder={'整理项目线索\n陪伴日常写作'} aria-label="适合任务" /></label>
            <label className="role-create-field"><span>不建议任务 <small>{taskBoundaryItems(createUnsuitableTasks).length}/4，每行一项</small></span><textarea rows={4} maxLength={324} value={createUnsuitableTasks} onChange={(event) => setCreateUnsuitableTasks(event.target.value)} placeholder={'高风险独立决定\n超出证据范围的判断'} aria-label="不建议任务" /></label>
          </div>
          <fieldset><legend>陪伴阶段</legend><div className="role-timeline-options">{timelineOptions.map((option) => <label key={option.value}><input type="radio" name="role-timeline" value={option.value} checked={timelineModel === option.value} onChange={() => setTimelineModel(option.value)} /><span><strong>{option.label}</strong><small>{option.caption}</small></span></label>)}</div></fieldset>
          <fieldset><legend>表达特征 <small>{createTraits.length}/5</small></legend><div className="role-trait-editor"><input maxLength={24} value={traitDraft} onChange={(event) => setTraitDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addTrait(); } }} placeholder="例如：温暖" aria-label="新增表达特征" /><IconButton label="添加表达特征" icon={<Plus size={15} />} disabled={!normalizeTrait(traitDraft) || createTraits.length >= 5} onClick={addTrait} tooltip /></div>{createTraits.length ? <div className="role-trait-list">{createTraits.map((trait) => <button type="button" key={trait} aria-label={`删除表达特征：${trait}`} onClick={() => setCreateTraits((current) => current.filter((item) => item !== trait))}><span>{trait}</span><X size={12} /></button>)}</div> : null}</fieldset>
          <fieldset><legend>可以在哪里陪你</legend><div className="role-mode-options"><label><input type="checkbox" checked disabled />一对一对话</label><label><input type="checkbox" checked={roomEnabled} onChange={(event) => setRoomEnabled(event.target.checked)} />参与多人协作</label></div><p className="role-mode-hint">这里只决定她能否加入协作空间。查资料、动手实现或独立验收等分工，会根据每次任务重新安排。</p></fieldset>
        </form>
        <DialogFooter><Button variant="quiet" disabled={roleCreating} onClick={() => setCreateOpen(false)}>取消</Button><Button type="submit" form="role-create-form" variant="primary" loading={roleCreating} disabled={!createDisplayName.trim() || !createTagline.trim() || !createSummary.trim() || !pendingTraits.length || !taskBoundariesValid(createSuitableTasks) || !taskBoundariesValid(createUnsuitableTasks)}>{editingPersona ? '保存伙伴' : '添加伙伴'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={Boolean(archiveTarget)} onOpenChange={(open) => { if (!open && !roleArchiving) { setArchiveTarget(null); setArchiveError(''); } }}>
      <DialogContent className="role-archive-dialog"><DialogHeader><DialogTitle>移除这个伙伴？</DialogTitle><DialogDescription>“{archiveTarget?.displayName}”会从新对话和协作空间的伙伴目录中移除；已有对话仍保留并可继续。</DialogDescription></DialogHeader>{archiveError ? <p className="role-create-error" role="alert">{archiveError}</p> : null}<DialogFooter><Button variant="quiet" disabled={roleArchiving} onClick={() => setArchiveTarget(null)}>取消</Button><Button variant="danger" leadingIcon={<Trash2 size={14} />} loading={roleArchiving} onClick={() => void archiveCompanion()}>移除伙伴</Button></DialogFooter></DialogContent>
    </Dialog>
  </>;
}

type ModelRouteDefinition = {
  id: 'session' | 'room' | 'tool';
  title: string;
  description: string;
  modelKey: 'sessionModelProfile' | 'roomPartnerModelProfile' | 'toolAgentModelProfile';
  thinkingKey: 'sessionThinkingLevel' | 'roomPartnerThinkingLevel' | 'toolAgentThinkingLevel';
  icon: ReactNode;
};

const MODEL_ROUTES: readonly ModelRouteDefinition[] = [
  {
    id: 'session',
    title: '普通对话',
    description: '你直接发起的 Session 与新对话',
    modelKey: 'sessionModelProfile',
    thinkingKey: 'sessionThinkingLevel',
    icon: <MessagesSquare size={18} />,
  },
  {
    id: 'room',
    title: 'Room Partner',
    description: '多人协作中的主持、研究、实现与复核节点',
    modelKey: 'roomPartnerModelProfile',
    thinkingKey: 'roomPartnerThinkingLevel',
    icon: <Network size={18} />,
  },
  {
    id: 'tool',
    title: 'Tool Agent',
    description: '由 Agent 作为工具派发的子 Agent',
    modelKey: 'toolAgentModelProfile',
    thinkingKey: 'toolAgentThinkingLevel',
    icon: <Bot size={18} />,
  },
];

function ModelRoutingPanel({
  catalog,
  draft,
  onChange,
  onOpenProviders,
  onSave,
  saved,
  saving,
}: {
  catalog: RoleModelCatalog;
  draft: AgentModelRouting | null;
  onChange: (value: AgentModelRouting) => void;
  onOpenProviders: () => void;
  onSave: () => void;
  saved: AgentModelRouting | null;
  saving: boolean;
}) {
  const models = useMemo(() => catalog.providers.flatMap((provider) => (
    provider.models.map((model) => ({ model, providerName: provider.displayName }))
  )), [catalog.providers]);
  const modelOptions = models.map(({ model, providerName }) => ({
    value: `${model.provider}/${model.id}`,
    label: `${model.name} · ${providerName || model.provider}`,
  }));
  const changed = Boolean(saved && draft && MODEL_ROUTES.some((route) => (
    saved[route.modelKey] !== draft[route.modelKey]
    || saved[route.thinkingKey] !== draft[route.thinkingKey]
  )));

  return <section className="model-routing" aria-labelledby="model-routing-title">
    <header>
      <span><small>运行路由</small><h2 id="model-routing-title">按职责选择模型</h2><p>只影响之后新建的运行；正在执行的 Session 不会被中途切换。</p></span>
      <Button variant="primary" size="small" leadingIcon={<Save size={14} />} loading={saving} disabled={!changed} onClick={onSave}>保存模型路由</Button>
    </header>
    {!draft ? <div className="model-routing__empty" role="alert"><BrainCircuit size={18} /><span><strong>模型路由暂时不可用</strong><small>配置版本未知，所以不会猜测或覆盖现有设置。</small></span><Button variant="quiet" size="small" onClick={onOpenProviders}>检查模型配置</Button></div> : !models.length ? <div className="model-routing__empty"><BrainCircuit size={18} /><span><strong>还没有可选模型</strong><small>先连接 Provider，再分别设置普通对话、Room Partner 与 Tool Agent。</small></span><Button variant="quiet" size="small" onClick={onOpenProviders}>连接模型</Button></div> : <div className="model-routing__rows">
      {MODEL_ROUTES.map((route) => {
        const selected = models.find(({ model }) => `${model.provider}/${model.id}` === draft[route.modelKey]);
        const levels = selected?.model.thinkingLevels?.length ? selected.model.thinkingLevels : ['off'];
        return <article data-route={route.id} key={route.id}>
          <span className="model-routing__route-icon">{route.icon}</span>
          <span className="model-routing__route-copy"><strong>{route.title}</strong><small>{route.description}</small></span>
          <label><span>模型</span><Select aria-label={`${route.title}默认模型`} value={draft[route.modelKey]} options={modelOptions} onValueChange={(value) => {
            const next = models.find(({ model }) => `${model.provider}/${model.id}` === value)?.model;
            const nextLevels = next?.thinkingLevels?.length ? next.thinkingLevels : ['off'];
            onChange({
              ...draft,
              [route.modelKey]: value,
              [route.thinkingKey]: nextLevels.includes(draft[route.thinkingKey] as never)
                ? draft[route.thinkingKey]
                : nextLevels[0] ?? 'off',
            });
          }} /></label>
          <label><span>思考</span><Select aria-label={`${route.title}默认思考强度`} value={draft[route.thinkingKey]} options={levels.map((level) => ({ value: level, label: thinkingLabel(level) }))} onValueChange={(value) => onChange({ ...draft, [route.thinkingKey]: value })} /></label>
        </article>;
      })}
    </div>}
  </section>;
}

function PersonaInspector({
  canChangeDefault,
  defaulted,
  defaultSaving,
  onArchive,
  onCopy,
  onEdit,
  onSetDefault,
  onStart,
  persona,
  starting,
  onOpenGrowth,
}: {
  canChangeDefault: boolean;
  defaulted: boolean;
  defaultSaving: boolean;
  onArchive: () => void;
  onCopy: () => void;
  onEdit: () => void;
  onSetDefault: () => void;
  onStart: () => void;
  persona: AgentPersonaV1;
  starting: boolean;
  onOpenGrowth: () => void;
}) {
  const phase = personaPhase(persona);
  const expressionTraits = personaExpressionTraits(persona);
  const fixed = persona.defaults.modelPolicy === 'fixed';
  return (
    <aside className="role-inspector companion-inspector" data-accent={persona.visualProfile.accentToken}>
      <div className="role-inspector__hero">
        <PersonaAvatar persona={persona} size="hero" />
        <span>
          <small>{fixed ? '内置伙伴 · 复制后可以调整' : '我的伙伴 · 可以调整'}</small>
          <h2>{persona.displayName}</h2>
          <p>{persona.summary}</p>
        </span>
      </div>
      <div className="companion-actions">
        <Button variant="primary" size="small" loading={starting} leadingIcon={<MessageCirclePlus size={15} />} onClick={onStart}>开始对话</Button>
        <Button variant="quiet" size="small" onClick={fixed ? onCopy : onEdit}>{fixed ? '复制为我的伙伴' : '编辑伙伴'}</Button>
      </div>
      <section className="companion-fit" aria-label="伙伴能力边界">
        <div><header><Sparkles size={15} /><strong>适合交给她</strong></header><ul>{persona.runtimeCharacteristics.suitableTasks.map((task) => <li key={task}>{publicTaskLabel(task)}</li>)}</ul></div>
        <div><header><ShieldCheck size={15} /><strong>不建议交给她</strong></header><ul>{persona.runtimeCharacteristics.unsuitableTasks.map((task) => <li key={task}>{task}</li>)}</ul></div>
      </section>
      <section className="companion-expression">
        <header><strong>表达特征</strong><small>{phase.label}</small></header>
        <div>{expressionTraits.map((trait) => <span key={trait}>{trait}</span>)}</div>
      </section>
      <div className="companion-links">
        <Button variant="quiet" size="small" leadingIcon={<BookOpen size={14} />} onClick={onOpenGrowth}>她记住的成长</Button>
        {defaulted ? <span className="companion-default-state"><Star size={13} />新对话默认伙伴</span> : <Button variant="quiet" size="small" leadingIcon={<Star size={14} />} loading={defaultSaving} disabled={!canChangeDefault} onClick={onSetDefault}>设为默认</Button>}
        {fixed ? null : <Button variant="quiet" size="small" leadingIcon={<Trash2 size={14} />} disabled={defaulted} title={defaulted ? '请先选择另一位默认伙伴' : undefined} onClick={onArchive}>移除伙伴</Button>}
      </div>
      <details className="role-runtime-disclosure">
        <summary>
          <Cpu size={15} />
          <span><strong>身份与运行边界</strong><small>模型由上方的职责路由统一决定</small></span>
        </summary>
        <div className="role-runtime-disclosure__body">
          <dl>
            <div><dt>可用方式</dt><dd>{persona.selectableModes.includes('coordinator') ? '一对一对话 · 多人协作' : '一对一对话'}</dd></div>
            <div><dt>工具边界</dt><dd>按任务调用已连接工具，敏感操作仍需确认</dd></div>
            <div><dt>默认模型</dt><dd>普通对话、Room Partner 与 Tool Agent 分别继承页面上方的运行路由</dd></div>
            <div><dt>Room 职责</dt><dd>查资料、动手实现或独立验收等职责由每次 Room 的 WorkItem 决定</dd></div>
          </dl>
          <DefinitionAudit kind="伙伴定义" summary={`${persona.tagline}；${persona.summary}`} version={persona.version} source={fixed ? '内置伙伴目录' : '用户自定义伙伴'} />
        </div>
      </details>
    </aside>
  );
}

function PersonaGrowthInspector({ persona, onBack }: { persona: AgentPersonaV1; onBack: () => void }) {
  const transport = useControlTransport();
  const [catalog, setCatalog] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [selectedDraftId, setSelectedDraftId] = useState('');
  const [traitIndexes, setTraitIndexes] = useState<number[]>([]);
  const [capabilityIndexes, setCapabilityIndexes] = useState<number[]>([]);
  const [lessonIndexes, setLessonIndexes] = useState<number[]>([]);
  const [commitmentIndexes, setCommitmentIndexes] = useState<number[]>([]);
  const [mutationPending, setMutationPending] = useState(false);
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    void transport.request<Record<string, unknown>>({
      pathId: 'agent.roleBook.get',
      query: { roleId: persona.roleId, roleVersion: persona.version, limit: 30 },
    }).then((value) => {
      if (!active) return;
      const response = ensureControlOk(value);
      const drafts = roleBookDailyDrafts(response);
      setCatalog(response);
      setSelectedDraftId((current) => drafts.some((draft) => draft.draftId === current)
        ? current
        : drafts.find((draft) => !draft.decision)?.draftId ?? drafts[0]?.draftId ?? '');
    }).catch((cause) => {
      if (active) setError(publicErrorText(cause, '成长档案暂时无法读取。'));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [persona.roleId, persona.version, refreshVersion, transport]);

  useEffect(() => {
    setTraitIndexes([]);
    setCapabilityIndexes([]);
    setLessonIndexes([]);
    setCommitmentIndexes([]);
  }, [selectedDraftId, persona.roleId, persona.version]);

  const activeRevision = record(catalog?.active);
  const hasActiveRevision = Object.keys(activeRevision).length > 0;
  const sections = record(activeRevision.sections);
  const drafts = roleBookDailyDrafts(catalog);
  const selectedDraft = drafts.find((draft) => draft.draftId === selectedDraftId);
  const history = roleBookHistory(catalog);

  async function activateSelection(selection: RoleBookActivationSelection): Promise<void> {
    if (mutationPending) return;
    setMutationPending(true);
    setError('');
    try {
      const preview = ensureControlOk(await transport.request<Record<string, unknown>>({
        pathId: 'agent.roleBook.activation.preview',
        body: selection,
      }));
      const response = ensureControlOk(await transport.request<Record<string, unknown>>({
        pathId: 'agent.roleBook.activation.apply',
        body: {
          ...selection,
          previewToken: textValue(preview.previewToken),
          payloadSha256: textValue(preview.payloadSha256),
          confirmText: 'apply',
        },
      }));
      setReceipt(response);
      setRefreshVersion((value) => value + 1);
    } catch (cause) {
      setError(publicErrorText(cause, '暂时无法采用这些成长建议。'));
    } finally {
      setMutationPending(false);
    }
  }

  async function decideDraft(decision: 'rejected' | 'deferred'): Promise<void> {
    if (!selectedDraft || mutationPending) return;
    setMutationPending(true);
    setError('');
    try {
      ensureControlOk(await transport.request<Record<string, unknown>>({
        pathId: 'agent.roleBook.draft.decision',
        body: {
          roleId: persona.roleId,
          roleVersion: persona.version,
          draftId: selectedDraft.draftId,
          decision,
        },
      }));
      setRefreshVersion((value) => value + 1);
    } catch (cause) {
      setError(publicErrorText(cause, '暂时无法保存这次处理结果。'));
    } finally {
      setMutationPending(false);
    }
  }

  async function rollbackActivation(): Promise<void> {
    if (!receipt || mutationPending) return;
    setMutationPending(true);
    setError('');
    try {
      ensureControlOk(await transport.request<Record<string, unknown>>({
        pathId: 'agent.roleBook.activation.rollback',
        body: {
          receiptId: textValue(receipt.receiptId),
          rollbackToken: textValue(receipt.rollbackToken),
          payloadSha256: textValue(receipt.payloadSha256),
          confirmText: 'rollback',
        },
      }));
      setReceipt(null);
      setRefreshVersion((value) => value + 1);
    } catch (cause) {
      setError(publicErrorText(cause, '暂时无法撤销这次采用。'));
    } finally {
      setMutationPending(false);
    }
  }

  const selectedCount = traitIndexes.length
    + capabilityIndexes.length
    + lessonIndexes.length
    + commitmentIndexes.length;
  const availableProposalCount = selectedDraft
    ? selectedDraft.traitProposals.length
      + selectedDraft.capabilityProposals.length
      + selectedDraft.lessonProposals.length
      + selectedDraft.commitmentProposals.length
    : 0;
  return <aside className="role-inspector role-book-inspector" data-accent={persona.visualProfile.accentToken}>
    <div className="role-inspector__hero"><PersonaAvatar persona={persona} size="hero" /><span><small>成长档案</small><h2>{persona.displayName}</h2><p>{loading ? '正在读取…' : hasActiveRevision ? `第 ${numberValue(activeRevision.revisionNumber)} 版` : '还没有成长记录'}</p></span></div>
    <Button variant="quiet" size="small" onClick={onBack}>返回伙伴</Button>
    {error ? <p className="role-book-error" role="alert">{error}</p> : null}
    {!loading && catalog ? <>
      <section className="role-book-active" aria-label="当前成长档案">
        <header><span><BookOpen size={15} /><strong>当前版本</strong></span><small>{hasActiveRevision ? textValue(activeRevision.status) === 'active' ? '已启用' : textValue(activeRevision.status) : '尚未建立'}</small></header>
        <div className="role-book-counts">
          <span><b>{arrayValue(sections.personality).length}</b>协作特征</span>
          <span><b>{arrayValue(sections.capabilities).length}</b>已验证能力</span>
          <span><b>{arrayValue(sections.recentWork).length}</b>近期工作</span>
          <span><b>{arrayValue(sections.lessonsAndLimits).length}</b>经验边界</span>
        </div>
      </section>
      <section className="role-book-review" aria-label="待确认的成长建议">
        <header><span><Sparkles size={15} /><strong>待审草案</strong></span><small>{drafts.filter((draft) => !draft.decision).length} 个</small></header>
        {drafts.length ? <>
          <div className="role-book-draft-tabs">{drafts.map((draft) => <button type="button" key={draft.draftId} aria-current={draft.draftId === selectedDraftId} onClick={() => setSelectedDraftId(draft.draftId)}><span>{new Date(draft.createdAtMs).toLocaleDateString('zh-CN')}</span><small>{draft.decision?.decision === 'accepted' ? '已采用' : draft.decision?.decision === 'rejected' ? '已忽略' : draft.decision?.decision === 'deferred' ? '稍后处理' : '待审'}</small></button>)}</div>
          {selectedDraft ? <div className="role-book-proposals">
            {selectedDraft.traitProposals.length ? <fieldset><legend>协作特征</legend>{selectedDraft.traitProposals.map((proposal, index) => <label key={`${proposal.text}:${index}`}><input type="checkbox" checked={traitIndexes.includes(index)} onChange={() => setTraitIndexes(toggleIndex(traitIndexes, index))} /><span>{proposal.text}</span><small>{Math.round(proposal.confidence * 100)}%</small></label>)}</fieldset> : null}
            {selectedDraft.capabilityProposals.length ? <fieldset><legend>能力画像</legend>{selectedDraft.capabilityProposals.map((proposal, index) => <label key={`${proposal.text}:${index}`}><input type="checkbox" checked={capabilityIndexes.includes(index)} onChange={() => setCapabilityIndexes(toggleIndex(capabilityIndexes, index))} /><span>{proposal.text}</span><small>{Math.round(proposal.confidence * 100)}%</small></label>)}</fieldset> : null}
            {selectedDraft.lessonProposals.length ? <fieldset><legend>经验与边界</legend>{selectedDraft.lessonProposals.map((proposal, index) => <label key={`${proposal.text}:${index}`}><input type="checkbox" checked={lessonIndexes.includes(index)} onChange={() => setLessonIndexes(toggleIndex(lessonIndexes, index))} /><span>{proposal.text}</span><small>{Math.round(proposal.confidence * 100)}%</small></label>)}</fieldset> : null}
            {selectedDraft.commitmentProposals.length ? <fieldset><legend>当前承诺</legend>{selectedDraft.commitmentProposals.map((proposal, index) => <label key={`${proposal.text}:${index}`}><input type="checkbox" checked={commitmentIndexes.includes(index)} onChange={() => setCommitmentIndexes(toggleIndex(commitmentIndexes, index))} /><span>{proposal.text}</span><small>{Math.round(proposal.confidence * 100)}%</small></label>)}</fieldset> : null}
            {!availableProposalCount ? <p className="roles-empty">{roleBookDraftEmptyText(selectedDraft.proposalStatus)}</p> : null}
            <div className="role-book-actions"><Button variant="quiet" size="small" disabled={mutationPending} onClick={() => void decideDraft('deferred')}>稍后</Button><Button variant="quiet" size="small" disabled={mutationPending} onClick={() => void decideDraft('rejected')}>忽略</Button><Button variant="primary" size="small" leadingIcon={<Check size={14} />} loading={mutationPending} disabled={!selectedCount} onClick={() => void activateSelection({ roleId: persona.roleId, roleVersion: persona.version, revisionId: '', draftId: selectedDraft.draftId, traitIndexes, capabilityIndexes, lessonIndexes, commitmentIndexes })}>采用所选内容</Button></div>
          </div> : null}
        </> : <p className="roles-empty">当前没有待审草案。</p>}
      </section>
      {history.some((revision) => revision.status === 'draft') ? <section className="role-book-history" aria-label={`${persona.displayName}整理的成长建议`}><header><span><BrainCircuit size={15} /><strong>{persona.displayName}整理的建议</strong></span></header>{history.filter((revision) => revision.status === 'draft').map((revision) => <div key={revision.revisionId}><span><b>第 {revision.revisionNumber} 版</b><small>{revision.changeSummary || '等待你确认'}</small></span><Button variant="quiet" size="small" loading={mutationPending} onClick={() => void activateSelection({ roleId: persona.roleId, roleVersion: persona.version, revisionId: revision.revisionId, draftId: '', traitIndexes: [], capabilityIndexes: [], lessonIndexes: [], commitmentIndexes: [] })}>采用这版</Button></div>)}</section> : null}
      {receipt && Boolean(receipt.rollbackAvailable) ? <Button variant="quiet" size="small" leadingIcon={<RotateCcw size={14} />} loading={mutationPending} onClick={() => void rollbackActivation()}>撤销本次采用</Button> : null}
    </> : null}
  </aside>;
}

function roleBookDraftEmptyText(status: string): string {
  return {
    no_conversation_evidence: '这段时间没有可用于成长档案的对话证据；可以稍后处理或忽略这份空草案。',
    no_eligible_evidence: '这段时间没有符合长期成长档案条件的变化；可以稍后处理或忽略这份空草案。',
    not_configured: '成长整理尚未配置，因此没有生成可审阅的变化。',
    unsupported: '当前模型不支持成长整理，因此没有生成可审阅的变化。',
    failed: '这次成长整理没有完成；原有成长档案未被修改。',
  }[status] ?? '这份草案没有可采用的变化；原有成长档案未被修改。';
}

function publicTaskLabel(value: string): string {
  return value === '多 Agent 主持和独立验收' ? '多伙伴主持和独立验收' : value;
}

function DefinitionAudit({ kind, source, summary, version }: { kind: string; source: string; summary: string; version: string }) {
  return <details className="definition-audit"><summary><ShieldCheck size={14} /><span><strong>查看伙伴设定说明</strong><small>已检查 · 内容完整</small></span></summary><dl><div><dt>类型</dt><dd>{kind}</dd></div><div><dt>版本</dt><dd>{version}</dd></div><div><dt>来源</dt><dd>{source}</dd></div><div><dt>摘要</dt><dd>{summary}</dd></div></dl><p>这里只展示便于理解的设定摘要。新对话会稳定使用这份已保存的伙伴设定。</p></details>;
}

function taskBoundaryItems(value: string): string[] {
  const seen = new Set<string>();
  return value.split(/\r?\n/).map((item) => item.trim()).filter((item) => {
    const key = item.toLocaleLowerCase();
    if (!item || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function taskBoundariesValid(value: string): boolean {
  const items = taskBoundaryItems(value);
  return items.length >= 1 && items.length <= 4 && items.every((item) => item.length <= 80);
}
