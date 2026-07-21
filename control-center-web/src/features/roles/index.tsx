import {
  BookOpen,
  BrainCircuit,
  Check,
  Cpu,
  MessageCirclePlus,
  Plus,
  RotateCcw,
  ShieldCheck,
  Save,
  Sparkles,
  Star,
  Trash2,
  UserRoundPlus,
  Zap,
  X,
} from 'lucide-react';
import { useEffect, useState } from 'react';
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
  createdSessionId,
  ensureControlOk,
  modelDisplayName,
  normalizeTrait,
  normalizedTraits,
  numberValue,
  personaExpressionTraits,
  personaPhase,
  record,
  roleBookDailyDrafts,
  roleBookDiffSections,
  roleBookHistory,
  roleModelCatalog,
  textValue,
  thinkingLabel,
  timelineOptions,
  toggleIndex,
  type AgentDefaultCompanion,
  type RoleBookActivationSelection,
  type RoleBookDailyDraft,
  type RoleBookDiffItem,
  type RoleBookDiffSection,
  type RoleBookProposal,
  type RoleModelCatalog,
  type TimelineModel,
} from './role-model';
import './roles.css';

export function RolesFeature() {
  const transport = useControlTransport();
  const navigate = useNavigate();
  const [view, setView] = useState<'companions' | 'growth'>('companions');
  const [personas, setPersonas] = useState<AgentPersonaV1[]>(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas : []);
  const [modelCatalog, setModelCatalog] = useState<RoleModelCatalog>({ providers: [] });
  const [selectedPersona, setSelectedPersona] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas[0]?.roleId ?? '' : '');
  const [sessionCreating, setSessionCreating] = useState(false);
  const [roleCreating, setRoleCreating] = useState(false);
  const [roleDefaultsSaving, setRoleDefaultsSaving] = useState(false);
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
    void Promise.allSettled([
      transport.request({ pathId: 'agent.roles.list' }),
      transport.request({ pathId: 'agent.role.models' }),
      transport.request({ pathId: 'agent.configuration.get' }),
    ]).then(([roleResult, modelResult, configurationResult]) => {
      if (!active) return;
      const errors: string[] = [];
      if (roleResult.status === 'fulfilled') {
        const roles = roleItems(roleResult.value);
        if (roles.length || !(__CONTROL_PREVIEW__ && transport.kind === 'mock')) {
          setPersonas(roles);
          setSelectedPersona((current) => roles.some((item) => item.roleId === current) ? current : roles[0]?.roleId ?? '');
        }
      } else {
        errors.push(`角色目录：${publicErrorText(roleResult.reason, '暂时无法读取，请稍后重试。')}`);
      }
      if (modelResult.status === 'fulfilled') {
        setModelCatalog(roleModelCatalog(modelResult.value));
      }
      if (configurationResult.status === 'fulfilled') {
        setDefaultCompanion(agentDefaultCompanion(configurationResult.value));
      }
      setCatalogNotice(errors.join('；'));
    });
    return () => { active = false; };
  }, [transport]);
  const persona = personas.find((item) => item.roleId === selectedPersona);
  const notice = [catalogNotice, actionNotice].filter(Boolean).join('；');
  const personaIsDefault = Boolean(persona && defaultCompanion
    && persona.roleId === defaultCompanion.roleId
    && persona.version === defaultCompanion.roleVersion);

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

  function beginRoleCreation(): void {
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
      if (!created) throw new Error('服务端没有返回可验证的角色。');
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

  async function saveRoleRuntimeDefaults(modelProfile: string, thinkingLevel: string): Promise<void> {
    if (!persona || roleDefaultsSaving) return;
    const separator = modelProfile.indexOf('/');
    if (separator <= 0 || separator === modelProfile.length - 1) return;
    setRoleDefaultsSaving(true);
    setActionNotice('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.role.runtimeDefaults.update',
        body: {
          roleId: persona.roleId,
          roleVersion: persona.version,
          provider: modelProfile.slice(0, separator),
          modelId: modelProfile.slice(separator + 1),
          thinkingLevel,
        },
      });
      const [updated] = roleItems({ items: [record(response).role] });
      if (!updated) throw new Error('服务端没有返回可验证的角色默认设置。');
      setPersonas((current) => current.map((item) => (
        item.roleId === updated.roleId && item.version === updated.version ? updated : item
      )));
      setActionNotice(`${updated.displayName} 的默认模型已保存。`);
    } catch (error) {
      setActionNotice(publicErrorText(error, '角色默认模型暂时无法保存。'));
    } finally {
      setRoleDefaultsSaving(false);
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
      if (!updated) throw new Error('服务端没有返回可验证的默认伙伴设置。');
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
      <header className="roles-header"><span><h2>Agent 伙伴</h2><p>选择伙伴开始对话；Room 成员、岗位和任务交接只在 Room 内管理</p></span>{view === 'companions' ? <div className="roles-header-actions"><Button variant="quiet" size="small" leadingIcon={<UserRoundPlus size={15} />} onClick={beginRoleCreation}>添加伙伴</Button></div> : null}</header>
      {notice ? <p className="roles-notice" role="status">{notice}</p> : null}
      <div className="roles-layout">
          <section className="persona-grid" aria-label="伙伴目录">{personas.length ? personas.map((item) => { const builtin = item.defaults.modelPolicy === 'fixed'; const isDefault = item.roleId === defaultCompanion?.roleId && item.version === defaultCompanion.roleVersion; return <button type="button" key={`${item.roleId}:${item.version}`} data-accent={item.visualProfile.accentToken} aria-current={item.roleId === selectedPersona} onClick={() => { setSelectedPersona(item.roleId); setActionNotice(''); }}><PersonaAvatar persona={item} size="large" /><span className="persona-grid__copy"><strong>{item.displayName}</strong><small>{item.tagline}</small></span><div className="persona-grid__badges"><i className="persona-grid__kind" data-kind={builtin ? 'builtin' : 'custom'}>{builtin ? '内置只读' : '我的伙伴'}</i>{isDefault ? <em className="persona-grid__default">默认</em> : null}</div></button>; }) : <p className="roles-empty">本机还没有可用伙伴。</p>}</section>
          {persona && view === 'companions' ? <PersonaInspector canChangeDefault={Boolean(defaultCompanion && defaultCompanion.revision > 0)} catalog={modelCatalog} defaulted={personaIsDefault} defaultSaving={defaultSaving} persona={persona} saving={roleDefaultsSaving} onSave={saveRoleRuntimeDefaults} onOpenGrowth={() => setView('growth')} onEdit={() => beginRoleEdit(persona)} onCopy={() => beginRoleCopy(persona)} onSetDefault={() => void makeDefaultCompanion()} onArchive={() => { setArchiveError(''); setArchiveTarget(persona); }} onStart={() => void startPersonaSession()} starting={sessionCreating} /> : null}
          {persona && view === 'growth' ? <PersonaGrowthInspector persona={persona} onBack={() => setView('companions')} /> : null}
      </div>
    </main>
    <Dialog open={createOpen} onOpenChange={(open) => { if (!roleCreating) { setCreateOpen(open); if (!open) setCreateError(''); } }}>
      <DialogContent className="role-create-dialog">
        <DialogHeader><DialogTitle>{editingPersona ? '编辑伙伴' : '添加伙伴'}</DialogTitle><DialogDescription>{editingPersona ? '修改会用于之后消息的称呼、表达方式和陪伴阶段；工具与安全边界仍由系统管理。' : '从内置伙伴出发，或创建一位更贴近你的长期 Agent 伙伴。模型和工具在运行设置中独立管理。'}</DialogDescription></DialogHeader>
        <form id="role-create-form" className="role-create-form" onSubmit={(event) => { event.preventDefault(); void createRole(); }}>
          {createError ? <p className="role-create-error" role="alert">{createError}</p> : null}
          <div className="role-create-two-columns">
            <label className="role-create-field"><span>角色名</span><input autoFocus maxLength={40} value={createDisplayName} onChange={(event) => setCreateDisplayName(event.target.value)} placeholder="例如：智鼬·晨光" aria-label="角色名" /></label>
            <label className="role-create-field"><span>一句话介绍</span><input maxLength={80} value={createTagline} onChange={(event) => setCreateTagline(event.target.value)} placeholder="她会怎样陪你" aria-label="角色一句话介绍" /></label>
          </div>
          <label className="role-create-field"><span>角色说明</span><textarea rows={3} maxLength={180} value={createSummary} onChange={(event) => setCreateSummary(event.target.value)} placeholder="她更适合陪你完成哪些事情" aria-label="角色说明" /></label>
          <div className="role-create-two-columns role-create-boundaries">
            <label className="role-create-field"><span>适合任务 <small>{taskBoundaryItems(createSuitableTasks).length}/4，每行一项</small></span><textarea rows={4} maxLength={324} value={createSuitableTasks} onChange={(event) => setCreateSuitableTasks(event.target.value)} placeholder={'整理项目线索\n陪伴日常写作'} aria-label="适合任务" /></label>
            <label className="role-create-field"><span>不建议任务 <small>{taskBoundaryItems(createUnsuitableTasks).length}/4，每行一项</small></span><textarea rows={4} maxLength={324} value={createUnsuitableTasks} onChange={(event) => setCreateUnsuitableTasks(event.target.value)} placeholder={'高风险独立决定\n超出证据范围的判断'} aria-label="不建议任务" /></label>
          </div>
          <fieldset><legend>陪伴阶段</legend><div className="role-timeline-options">{timelineOptions.map((option) => <label key={option.value}><input type="radio" name="role-timeline" value={option.value} checked={timelineModel === option.value} onChange={() => setTimelineModel(option.value)} /><span><strong>{option.label}</strong><small>{option.caption}</small></span></label>)}</div></fieldset>
          <fieldset><legend>表达特征 <small>{createTraits.length}/5</small></legend><div className="role-trait-editor"><input maxLength={24} value={traitDraft} onChange={(event) => setTraitDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addTrait(); } }} placeholder="例如：温暖" aria-label="新增表达特征" /><IconButton label="添加表达特征" icon={<Plus size={15} />} disabled={!normalizeTrait(traitDraft) || createTraits.length >= 5} onClick={addTrait} tooltip /></div>{createTraits.length ? <div className="role-trait-list">{createTraits.map((trait) => <button type="button" key={trait} aria-label={`删除表达特征：${trait}`} onClick={() => setCreateTraits((current) => current.filter((item) => item !== trait))}><span>{trait}</span><X size={12} /></button>)}</div> : null}</fieldset>
          <fieldset><legend>可用方式</legend><div className="role-mode-options"><label><input type="checkbox" checked disabled />陪伴对话</label><label><input type="checkbox" checked={roomEnabled} onChange={(event) => setRoomEnabled(event.target.checked)} />允许加入 Room</label></div><p className="role-mode-hint">只表示她可成为 Room 成员；研究、执行、复核等岗位由当前任务动态分派，不固定成主持人。</p></fieldset>
        </form>
        <DialogFooter><Button variant="quiet" disabled={roleCreating} onClick={() => setCreateOpen(false)}>取消</Button><Button type="submit" form="role-create-form" variant="primary" loading={roleCreating} disabled={!createDisplayName.trim() || !createTagline.trim() || !createSummary.trim() || !pendingTraits.length || !taskBoundariesValid(createSuitableTasks) || !taskBoundariesValid(createUnsuitableTasks)}>{editingPersona ? '保存伙伴' : '添加伙伴'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={Boolean(archiveTarget)} onOpenChange={(open) => { if (!open && !roleArchiving) { setArchiveTarget(null); setArchiveError(''); } }}>
      <DialogContent><DialogHeader><DialogTitle>移除这个伙伴？</DialogTitle><DialogDescription>“{archiveTarget?.displayName}”会从新对话和 Room 的伙伴目录中移除；已有对话仍保留并可继续。</DialogDescription></DialogHeader>{archiveError ? <p className="role-create-error" role="alert">{archiveError}</p> : null}<DialogFooter><Button variant="quiet" disabled={roleArchiving} onClick={() => setArchiveTarget(null)}>取消</Button><Button variant="danger" leadingIcon={<Trash2 size={14} />} loading={roleArchiving} onClick={() => void archiveCompanion()}>移除伙伴</Button></DialogFooter></DialogContent>
    </Dialog>
  </>;
}

function PersonaInspector({
  canChangeDefault,
  catalog,
  defaulted,
  defaultSaving,
  onArchive,
  onCopy,
  onEdit,
  onSetDefault,
  onStart,
  onSave,
  persona,
  saving,
  starting,
  onOpenGrowth,
}: {
  canChangeDefault: boolean;
  catalog: RoleModelCatalog;
  defaulted: boolean;
  defaultSaving: boolean;
  onArchive: () => void;
  onCopy: () => void;
  onEdit: () => void;
  onSetDefault: () => void;
  onStart: () => void;
  onSave: (modelProfile: string, thinkingLevel: string) => Promise<void>;
  persona: AgentPersonaV1;
  saving: boolean;
  starting: boolean;
  onOpenGrowth: () => void;
}) {
  const phase = personaPhase(persona);
  const expressionTraits = personaExpressionTraits(persona);
  const initialProfile = persona.defaults.modelProfile ?? '';
  const [modelProfile, setModelProfile] = useState(initialProfile);
  const [thinkingLevel, setThinkingLevel] = useState<string>(persona.defaults.thinkingLevel ?? 'off');
  useEffect(() => {
    setModelProfile(persona.defaults.modelProfile ?? '');
    setThinkingLevel(persona.defaults.thinkingLevel ?? 'off');
  }, [persona.roleId, persona.version, persona.defaults.modelProfile, persona.defaults.thinkingLevel]);
  const models = catalog.providers.flatMap((provider) => provider.models);
  const selectedModel = models.find((model) => `${model.provider}/${model.id}` === modelProfile);
  const thinkingLevels = selectedModel?.thinkingLevels?.length ? selectedModel.thinkingLevels : ['off'];
  const changed = modelProfile !== initialProfile || thinkingLevel !== (persona.defaults.thinkingLevel ?? 'off');
  const fixed = persona.defaults.modelPolicy === 'fixed';
  return <aside className="role-inspector companion-inspector" data-accent={persona.visualProfile.accentToken}>
    <div className="role-inspector__hero"><PersonaAvatar persona={persona} size="hero" /><span><small>{fixed ? '内置伙伴 · 只读' : '我的伙伴 · 可编辑'}</small><h3>{persona.displayName}</h3><p>{persona.summary}</p></span></div>
    <div className="companion-actions"><Button variant="primary" size="small" loading={starting} leadingIcon={<MessageCirclePlus size={15} />} onClick={onStart}>开始对话</Button><Button variant="quiet" size="small" onClick={fixed ? onCopy : onEdit}>{fixed ? '复制并自定义' : '编辑伙伴'}</Button></div>
    <section className="companion-fit" aria-label="伙伴能力边界"><div><header><Sparkles size={15} /><strong>适合交给她</strong></header><ul>{persona.runtimeCharacteristics.suitableTasks.map((task) => <li key={task}>{task}</li>)}</ul></div><div><header><ShieldCheck size={15} /><strong>不建议交给她</strong></header><ul>{persona.runtimeCharacteristics.unsuitableTasks.map((task) => <li key={task}>{task}</li>)}</ul></div></section>
    <section className="companion-expression"><header><strong>表达特征</strong><small>{phase.label}</small></header><div>{expressionTraits.map((trait) => <span key={trait}>{trait}</span>)}</div></section>
    <div className="companion-links"><Button variant="quiet" size="small" leadingIcon={<BookOpen size={14} />} onClick={onOpenGrowth}>角色记忆与成长档案</Button>{defaulted ? <span className="companion-default-state"><Star size={13} />新对话默认伙伴</span> : <Button variant="quiet" size="small" leadingIcon={<Star size={14} />} loading={defaultSaving} disabled={!canChangeDefault} onClick={onSetDefault}>设为默认</Button>}{fixed ? null : <Button variant="quiet" size="small" leadingIcon={<Trash2 size={14} />} disabled={defaulted} title={defaulted ? '请先选择另一位默认伙伴' : undefined} onClick={onArchive}>移除伙伴</Button>}</div>
    <details className="role-runtime-disclosure"><summary><Cpu size={15} /><span><strong>运行设置与定义</strong><small>{fixed ? '内置配置只读；复制后可自定义' : '只影响新对话的默认运行方式'}</small></span></summary><div className="role-runtime-disclosure__body"><dl><div><dt>可用方式</dt><dd>{persona.selectableModes.includes('coordinator') ? '陪伴对话 · 可加入 Room' : '陪伴对话'}</dd></div><div><dt>工具边界</dt><dd>按任务调用已连接工具，敏感操作仍需确认</dd></div></dl><section className="role-runtime-defaults" aria-label="伙伴运行默认设置"><header><span>{persona.roleId === 'companion-flash-v1' ? <Zap size={15} /> : <Cpu size={15} />}<strong>{fixed ? '内置模型' : '默认模型'}</strong></span><small>新对话自动使用</small></header>{fixed ? <div className="role-runtime-fixed"><span><b>{modelDisplayName(modelProfile)}</b><small>产品基线</small></span><span><b>推理强度</b><small>{thinkingLabel(thinkingLevel)}</small></span></div> : models.length ? <><label><span>模型</span><Select aria-label="角色默认模型" value={modelProfile} onValueChange={(value) => { setModelProfile(value); const next = models.find((model) => `${model.provider}/${model.id}` === value); const levels = next?.thinkingLevels?.length ? next.thinkingLevels : ['off']; if (!levels.includes(thinkingLevel)) setThinkingLevel(levels[0] ?? 'off'); }} options={models.map((model) => ({ value: `${model.provider}/${model.id}`, label: model.name }))} /></label><label><span>推理强度</span><Select aria-label="角色默认推理强度" value={thinkingLevel} onValueChange={setThinkingLevel} options={thinkingLevels.map((level) => ({ value: level, label: thinkingLabel(level) }))} /></label><Button variant="primary" size="small" leadingIcon={<Save size={14} />} loading={saving} disabled={!changed || !modelProfile} onClick={() => void onSave(modelProfile, thinkingLevel)}>保存默认设置</Button></> : <p><BrainCircuit size={15} />当前 Pi 模型目录不可用，请先在配置页完成模型配置。</p>}</section><DefinitionAudit kind="伙伴定义" summary={`${persona.tagline}；${persona.summary}`} version={persona.version} source={fixed ? '内置伙伴目录' : '用户自定义伙伴'} /></div></details>
  </aside>;
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
  const [pendingPreview, setPendingPreview] = useState<Record<string, unknown> | null>(null);
  const [pendingSelection, setPendingSelection] = useState<RoleBookActivationSelection | null>(null);
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
      if (active) setError(publicErrorText(cause, '角色书暂时无法读取。'));
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
    setPendingPreview(null);
    setPendingSelection(null);
  }, [selectedDraftId, persona.roleId, persona.version]);

  const activeRevision = record(catalog?.active);
  const sections = record(activeRevision.sections);
  const drafts = roleBookDailyDrafts(catalog);
  const selectedDraft = drafts.find((draft) => draft.draftId === selectedDraftId);
  const history = roleBookHistory(catalog);

  async function previewActivation(selection: RoleBookActivationSelection): Promise<void> {
    if (mutationPending) return;
    setMutationPending(true);
    setError('');
    try {
      const response = ensureControlOk(await transport.request<Record<string, unknown>>({
        pathId: 'agent.roleBook.activation.preview',
        body: selection,
      }));
      setPendingSelection(selection);
      setPendingPreview(response);
    } catch (cause) {
      setError(publicErrorText(cause, '角色书预览失败。'));
    } finally {
      setMutationPending(false);
    }
  }

  async function applyActivation(): Promise<void> {
    if (!pendingPreview || !pendingSelection || mutationPending) return;
    setMutationPending(true);
    setError('');
    try {
      const response = ensureControlOk(await transport.request<Record<string, unknown>>({
        pathId: 'agent.roleBook.activation.apply',
        body: {
          ...pendingSelection,
          previewToken: textValue(pendingPreview.previewToken),
          payloadSha256: textValue(pendingPreview.payloadSha256),
          confirmText: 'apply',
        },
      }));
      setReceipt(response);
      setPendingPreview(null);
      setPendingSelection(null);
      setRefreshVersion((value) => value + 1);
    } catch (cause) {
      setError(publicErrorText(cause, '角色书启用失败。'));
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
      setError(publicErrorText(cause, '角色书草案状态无法保存。'));
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
      setError(publicErrorText(cause, '角色书撤销失败。'));
    } finally {
      setMutationPending(false);
    }
  }

  const selectedCount = traitIndexes.length
    + capabilityIndexes.length
    + lessonIndexes.length
    + commitmentIndexes.length;
  const previewSummary = record(pendingPreview?.summary);
  const previewDiff = roleBookDiffSections(previewSummary.diff);
  return <aside className="role-inspector role-book-inspector" data-accent={persona.visualProfile.accentToken}>
    <div className="role-inspector__hero"><PersonaAvatar persona={persona} size="hero" /><span><small>成长档案</small><h3>{persona.displayName}</h3><p>{loading ? '正在读取…' : `Revision ${numberValue(activeRevision.revisionNumber) || 1}`}</p></span></div>
    <Button variant="quiet" size="small" onClick={onBack}>返回角色</Button>
    {error ? <p className="role-book-error" role="alert">{error}</p> : null}
    {!loading && catalog ? <>
      <section className="role-book-active" aria-label="当前角色书">
        <header><span><BookOpen size={15} /><strong>当前版本</strong></span><small>{textValue(activeRevision.status) === 'active' ? '已启用' : textValue(activeRevision.status)}</small></header>
        <div className="role-book-counts">
          <span><b>{arrayValue(sections.personality).length}</b>协作特征</span>
          <span><b>{arrayValue(sections.capabilities).length}</b>已验证能力</span>
          <span><b>{arrayValue(sections.recentWork).length}</b>近期工作</span>
          <span><b>{arrayValue(sections.lessonsAndLimits).length}</b>经验边界</span>
        </div>
      </section>
      <section className="role-book-review" aria-label="角色书待审草案">
        <header><span><Sparkles size={15} /><strong>待审草案</strong></span><small>{drafts.filter((draft) => !draft.decision).length} 个</small></header>
        {drafts.length ? <>
          <div className="role-book-draft-tabs">{drafts.map((draft) => <button type="button" key={draft.draftId} aria-current={draft.draftId === selectedDraftId} onClick={() => setSelectedDraftId(draft.draftId)}><span>{new Date(draft.createdAtMs).toLocaleDateString('zh-CN')}</span><small>{draft.decision?.decision === 'accepted' ? '已采用' : draft.decision?.decision === 'rejected' ? '已忽略' : draft.decision?.decision === 'deferred' ? '稍后处理' : '待审'}</small></button>)}</div>
          {selectedDraft ? <div className="role-book-proposals">
            {selectedDraft.traitProposals.length ? <fieldset><legend>协作特征</legend>{selectedDraft.traitProposals.map((proposal, index) => <label key={`${proposal.text}:${index}`}><input type="checkbox" checked={traitIndexes.includes(index)} onChange={() => setTraitIndexes(toggleIndex(traitIndexes, index))} /><span>{proposal.text}</span><small>{Math.round(proposal.confidence * 100)}%</small></label>)}</fieldset> : null}
            {selectedDraft.capabilityProposals.length ? <fieldset><legend>能力画像</legend>{selectedDraft.capabilityProposals.map((proposal, index) => <label key={`${proposal.text}:${index}`}><input type="checkbox" checked={capabilityIndexes.includes(index)} onChange={() => setCapabilityIndexes(toggleIndex(capabilityIndexes, index))} /><span>{proposal.text}</span><small>{Math.round(proposal.confidence * 100)}%</small></label>)}</fieldset> : null}
            {selectedDraft.lessonProposals.length ? <fieldset><legend>经验与边界</legend>{selectedDraft.lessonProposals.map((proposal, index) => <label key={`${proposal.text}:${index}`}><input type="checkbox" checked={lessonIndexes.includes(index)} onChange={() => setLessonIndexes(toggleIndex(lessonIndexes, index))} /><span>{proposal.text}</span><small>{Math.round(proposal.confidence * 100)}%</small></label>)}</fieldset> : null}
            {selectedDraft.commitmentProposals.length ? <fieldset><legend>当前承诺</legend>{selectedDraft.commitmentProposals.map((proposal, index) => <label key={`${proposal.text}:${index}`}><input type="checkbox" checked={commitmentIndexes.includes(index)} onChange={() => setCommitmentIndexes(toggleIndex(commitmentIndexes, index))} /><span>{proposal.text}</span><small>{Math.round(proposal.confidence * 100)}%</small></label>)}</fieldset> : null}
            <div className="role-book-actions"><Button variant="quiet" size="small" disabled={mutationPending} onClick={() => void decideDraft('deferred')}>稍后</Button><Button variant="quiet" size="small" disabled={mutationPending} onClick={() => void decideDraft('rejected')}>忽略</Button><Button variant="primary" size="small" leadingIcon={<Check size={14} />} loading={mutationPending} disabled={!selectedCount} onClick={() => void previewActivation({ roleId: persona.roleId, roleVersion: persona.version, revisionId: '', draftId: selectedDraft.draftId, traitIndexes, capabilityIndexes, lessonIndexes, commitmentIndexes })}>预览启用</Button></div>
          </div> : null}
        </> : <p className="roles-empty">当前没有待审草案。</p>}
      </section>
      {history.some((revision) => revision.status === 'draft') ? <section className="role-book-history" aria-label="Agent 提出的角色书版本"><header><span><BrainCircuit size={15} /><strong>Agent 草案</strong></span></header>{history.filter((revision) => revision.status === 'draft').map((revision) => <div key={revision.revisionId}><span><b>Revision {revision.revisionNumber}</b><small>{revision.changeSummary || '待审修订'}</small></span><Button variant="quiet" size="small" disabled={mutationPending} onClick={() => void previewActivation({ roleId: persona.roleId, roleVersion: persona.version, revisionId: revision.revisionId, draftId: '', traitIndexes: [], capabilityIndexes: [], lessonIndexes: [], commitmentIndexes: [] })}>预览</Button></div>)}</section> : null}
      {receipt && Boolean(receipt.rollbackAvailable) ? <Button variant="quiet" size="small" leadingIcon={<RotateCcw size={14} />} loading={mutationPending} onClick={() => void rollbackActivation()}>撤销本次启用</Button> : null}
    </> : null}
    <Dialog open={Boolean(pendingPreview)} onOpenChange={(open) => { if (!open && !mutationPending) { setPendingPreview(null); setPendingSelection(null); } }}>
      <DialogContent>
        <DialogHeader><DialogTitle>启用成长档案修订</DialogTitle><DialogDescription>R1 确认 · 已核验 {numberValue(previewSummary.evidenceCount)} 条证据</DialogDescription></DialogHeader>
        <ul className="role-book-preview-items">{arrayValue(previewSummary.items).map((item, index) => <li key={`${textValue(item)}:${index}`}>{textValue(item)}</li>)}</ul>
        <div className="role-book-preview-diff" aria-label="角色书逐项差异">
          {previewDiff.map((section) => <section key={section.section}>
            <header><strong>{section.label}</strong><small>+{section.added.length} / -{section.removed.length} / ~{section.changed.length}</small></header>
            {section.added.map((item) => <p key={`added:${item.itemId}`} data-change="added"><b>新增</b><span>{item.text}</span><small>{item.evidenceIds.length} 条证据</small></p>)}
            {section.removed.map((item) => <p key={`removed:${item.itemId}`} data-change="removed"><b>删除</b><span>{item.text}</span><small>{item.evidenceIds.length} 条证据</small></p>)}
            {section.changed.map((item) => <p key={`changed:${item.itemId}`} data-change="changed"><b>修改</b><span><del>{item.before.text}</del><ins>{item.after.text}</ins></span><small>{item.after.evidenceIds.length} 条证据</small></p>)}
          </section>)}
        </div>
        <DialogFooter><Button variant="quiet" disabled={mutationPending} onClick={() => { setPendingPreview(null); setPendingSelection(null); }}>取消</Button><Button variant="primary" loading={mutationPending} onClick={() => void applyActivation()}>确认启用</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </aside>;
}

function DefinitionAudit({ kind, source, summary, version }: { kind: string; source: string; summary: string; version: string }) {
  return <details className="definition-audit"><summary><ShieldCheck size={14} /><span><strong>Prompt 摘要与审计</strong><small>已审计 · 无占位符</small></span></summary><dl><div><dt>类型</dt><dd>{kind}</dd></div><div><dt>版本</dt><dd>{version}</dd></div><div><dt>来源</dt><dd>{source}</dd></div><div><dt>摘要</dt><dd>{summary}</dd></div></dl><p>这里只展示可解释摘要。完整系统 Prompt 由 Runtime 按版本装配，不在角色目录中泄露或临时拼接。</p></details>;
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
