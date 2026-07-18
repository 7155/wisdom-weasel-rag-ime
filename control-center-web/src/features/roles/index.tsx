import {
  BookOpen,
  Bot,
  BrainCircuit,
  Check,
  Cpu,
  Gauge,
  LockKeyhole,
  MessageCirclePlus,
  Plus,
  RotateCcw,
  ShieldCheck,
  Save,
  Sparkles,
  UserRoundPlus,
  Wrench,
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
  SegmentedControl,
} from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { AgentModelCatalogV1 } from '@/contracts/generated/agent-model-catalog.v1';
import type { AgentTemplateV1 } from '@/contracts/generated/agent-template.v1';
import { previewPersonas, previewTemplates } from '@/features/agent/preview-data';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { roleItems } from '@/features/agent/types';
import { publicErrorText } from '@/features/overview/management-ui';
import './roles.css';

export function RolesFeature() {
  const transport = useControlTransport();
  const navigate = useNavigate();
  const [view, setView] = useState<'personas' | 'roleBook' | 'templates'>('personas');
  const [personas, setPersonas] = useState<AgentPersonaV1[]>(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas : []);
  const [templates, setTemplates] = useState<AgentTemplateV1[]>(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewTemplates : []);
  const [modelCatalog, setModelCatalog] = useState<RoleModelCatalog>({ providers: [] });
  const [selectedPersona, setSelectedPersona] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas[0]?.roleId ?? '' : '');
  const [selectedTemplate, setSelectedTemplate] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewTemplates[0]?.templateId ?? '' : '');
  const [sessionCreating, setSessionCreating] = useState(false);
  const [roleCreating, setRoleCreating] = useState(false);
  const [roleDefaultsSaving, setRoleDefaultsSaving] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createDisplayName, setCreateDisplayName] = useState('');
  const [createTagline, setCreateTagline] = useState('');
  const [createSummary, setCreateSummary] = useState('');
  const [createTraits, setCreateTraits] = useState<string[]>([]);
  const [traitDraft, setTraitDraft] = useState('');
  const [timelineModel, setTimelineModel] = useState<TimelineModel>('terra');
  const [coordinatorEnabled, setCoordinatorEnabled] = useState(false);
  const [catalogNotice, setCatalogNotice] = useState('');
  const [actionNotice, setActionNotice] = useState('');
  const [createError, setCreateError] = useState('');
  useEffect(() => {
    let active = true;
    void Promise.allSettled([
      transport.request({ pathId: 'agent.roles.list' }),
      transport.request({ pathId: 'agent.subagents.templates' }),
      transport.request({ pathId: 'agent.role.models' }),
    ]).then(([roleResult, templateResult, modelResult]) => {
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
      if (templateResult.status === 'fulfilled') {
        const values = templateItems(templateResult.value);
        if (values.length || !(__CONTROL_PREVIEW__ && transport.kind === 'mock')) {
          setTemplates(values);
          setSelectedTemplate((current) => values.some((item) => item.templateId === current) ? current : values[0]?.templateId ?? '');
        }
      } else {
        errors.push(`Agent 模板：${publicErrorText(templateResult.reason, '暂时无法读取，请稍后重试。')}`);
      }
      if (modelResult.status === 'fulfilled') {
        setModelCatalog(roleModelCatalog(modelResult.value));
      }
      setCatalogNotice(errors.join('；'));
    });
    return () => { active = false; };
  }, [transport]);
  const persona = personas.find((item) => item.roleId === selectedPersona);
  const template = templates.find((item) => item.templateId === selectedTemplate);
  const notice = [catalogNotice, actionNotice].filter(Boolean).join('；');

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
    setTraitDraft('');
    setTimelineModel('terra');
    setCoordinatorEnabled(false);
    setActionNotice('');
    setCreateError('');
    setCreateOpen(true);
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
    if (!displayName || !tagline || !summary || !traits.length) return;
    setRoleCreating(true);
    setCreateError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.roles.create',
        body: {
          displayName,
          tagline,
          summary,
          traits,
          timelineModel,
          selectableModes: coordinatorEnabled
            ? ['assistant', 'coordinator']
            : ['assistant'],
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

  const pendingTraits = normalizedTraits(createTraits, traitDraft);

  return <>
    <main className="roles-feature" data-route-id="roles">
      <header className="roles-header"><span><h2>角色与 Agent 模板</h2><p>角色决定陪伴方式，模板决定任务能力</p></span><SegmentedControl aria-label="角色视图" value={view} onValueChange={(value) => setView(value as 'personas' | 'roleBook' | 'templates')} items={[{ value: 'personas', label: '角色' }, { value: 'roleBook', label: '角色书' }, { value: 'templates', label: 'Agent 模板' }]} />{view !== 'templates' ? <div className="roles-header-actions"><IconButton label="创建角色" icon={<UserRoundPlus size={16} />} onClick={beginRoleCreation} tooltip /><Button variant="primary" size="small" disabled={!persona} loading={sessionCreating} leadingIcon={<MessageCirclePlus size={15} />} onClick={() => void startPersonaSession()}>开始对话</Button></div> : null}</header>
      {notice ? <p className="roles-notice" role="status">{notice}</p> : null}
      {view !== 'templates' ? (
        <div className="roles-layout">
          <section className="persona-grid" aria-label="角色列表">{personas.length ? personas.map((item) => <button type="button" key={`${item.roleId}:${item.version}`} data-accent={item.visualProfile.accentToken} aria-current={item.roleId === selectedPersona} onClick={() => { setSelectedPersona(item.roleId); setActionNotice(''); }}><PersonaAvatar persona={item} size="large" /><span><strong>{item.displayName}</strong><small>{item.tagline}</small></span><div><b aria-label="角色阶段">{personaPhase(item).label}</b>{personaExpressionTraits(item).map((trait) => <i key={trait}>{trait}</i>)}</div></button>) : <p className="roles-empty">本机还没有可用角色。</p>}</section>
          {persona && view === 'personas' ? <PersonaInspector catalog={modelCatalog} persona={persona} saving={roleDefaultsSaving} onSave={saveRoleRuntimeDefaults} /> : null}
          {persona && view === 'roleBook' ? <RoleBookInspector persona={persona} /> : null}
        </div>
      ) : (
        <div className="roles-layout">
          <section className="template-list" aria-label="Agent 模板列表">{templates.length ? templates.map((item) => <button type="button" key={item.templateId} aria-current={item.templateId === selectedTemplate} onClick={() => setSelectedTemplate(item.templateId)}><span><Bot size={17} /></span><div><strong>{item.displayName}</strong><small>{item.summary}</small></div></button>) : <p className="roles-empty">本机还没有可用的任务模板。</p>}</section>
          {template ? <TemplateInspector template={template} /> : null}
        </div>
      )}
    </main>
    <Dialog open={createOpen} onOpenChange={(open) => { if (!roleCreating) { setCreateOpen(open); if (!open) setCreateError(''); } }}>
      <DialogContent className="role-create-dialog">
        <DialogHeader><DialogTitle>创建角色</DialogTitle><DialogDescription>给同一个智鼬设定名字、表达方式和陪伴阶段。实际对话模型由 Agent 中的 Pi 模型目录选择。</DialogDescription></DialogHeader>
        <form id="role-create-form" className="role-create-form" onSubmit={(event) => { event.preventDefault(); void createRole(); }}>
          {createError ? <p className="role-create-error" role="alert">{createError}</p> : null}
          <div className="role-create-two-columns">
            <label className="role-create-field"><span>角色名</span><input autoFocus maxLength={40} value={createDisplayName} onChange={(event) => setCreateDisplayName(event.target.value)} placeholder="例如：智鼬·晨光" aria-label="角色名" /></label>
            <label className="role-create-field"><span>一句话介绍</span><input maxLength={80} value={createTagline} onChange={(event) => setCreateTagline(event.target.value)} placeholder="她会怎样陪你" aria-label="角色一句话介绍" /></label>
          </div>
          <label className="role-create-field"><span>角色说明</span><textarea rows={3} maxLength={180} value={createSummary} onChange={(event) => setCreateSummary(event.target.value)} placeholder="她更适合陪你完成哪些事情" aria-label="角色说明" /></label>
          <fieldset><legend>陪伴阶段</legend><div className="role-timeline-options">{timelineOptions.map((option) => <label key={option.value}><input type="radio" name="role-timeline" value={option.value} checked={timelineModel === option.value} onChange={() => setTimelineModel(option.value)} /><span><strong>{option.label}</strong><small>{option.caption}</small></span></label>)}</div></fieldset>
          <fieldset><legend>表达特征 <small>{createTraits.length}/5</small></legend><div className="role-trait-editor"><input maxLength={24} value={traitDraft} onChange={(event) => setTraitDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addTrait(); } }} placeholder="例如：温暖" aria-label="新增表达特征" /><IconButton label="添加表达特征" icon={<Plus size={15} />} disabled={!normalizeTrait(traitDraft) || createTraits.length >= 5} onClick={addTrait} tooltip /></div>{createTraits.length ? <div className="role-trait-list">{createTraits.map((trait) => <button type="button" key={trait} aria-label={`删除表达特征：${trait}`} onClick={() => setCreateTraits((current) => current.filter((item) => item !== trait))}><span>{trait}</span><X size={12} /></button>)}</div> : null}</fieldset>
          <fieldset><legend>可用方式</legend><div className="role-mode-options"><label><input type="checkbox" checked disabled />陪伴对话</label><label><input type="checkbox" checked={coordinatorEnabled} onChange={(event) => setCoordinatorEnabled(event.target.checked)} />协作主持</label></div></fieldset>
        </form>
        <DialogFooter><Button variant="quiet" disabled={roleCreating} onClick={() => setCreateOpen(false)}>取消</Button><Button type="submit" form="role-create-form" variant="primary" loading={roleCreating} disabled={!createDisplayName.trim() || !createTagline.trim() || !createSummary.trim() || !pendingTraits.length}>创建角色</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}

type TimelineModel = 'luna' | 'terra' | 'sol';

const timelineOptions: ReadonlyArray<{ value: TimelineModel; label: string; caption: string }> = [
  { value: 'luna', label: '初识阶段', caption: '好奇、轻快，侧重认识与记录' },
  { value: 'terra', label: '此刻阶段', caption: '温暖、清晰，侧重回顾与整理' },
  { value: 'sol', label: '构筑阶段', caption: '沉稳、面向行动，侧重协作与推进' },
];

function PersonaInspector({
  catalog,
  onSave,
  persona,
  saving,
}: {
  catalog: RoleModelCatalog;
  onSave: (modelProfile: string, thinkingLevel: string) => Promise<void>;
  persona: AgentPersonaV1;
  saving: boolean;
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
  return <aside className="role-inspector" data-accent={persona.visualProfile.accentToken}><div className="role-inspector__hero"><PersonaAvatar persona={persona} size="hero" /><span><small>角色</small><h3>{persona.displayName}</h3><p>{persona.summary}</p></span></div><dl><div><dt><Gauge size={15} />陪伴阶段</dt><dd>{phase.label}</dd></div><div><dt><Sparkles size={15} />表达特征</dt><dd>{expressionTraits.length ? expressionTraits.join(' · ') : '自然'}</dd></div><div><dt><LockKeyhole size={15} />可用方式</dt><dd>{persona.selectableModes.map(modeLabel).join(' · ')}</dd></div><div><dt><ShieldCheck size={15} />操作确认</dt><dd>敏感操作由你确认</dd></div><div><dt><Wrench size={15} />工具使用</dt><dd>按任务调用已连接工具</dd></div></dl><section className="role-runtime-defaults" aria-label="角色运行默认设置"><header><span><Cpu size={15} /><strong>默认模型</strong></span><small>新对话自动使用</small></header>{models.length ? <><label><span>模型</span><Select aria-label="角色默认模型" value={modelProfile} onValueChange={(value) => { setModelProfile(value); const next = models.find((model) => `${model.provider}/${model.id}` === value); const levels = next?.thinkingLevels?.length ? next.thinkingLevels : ['off']; if (!levels.includes(thinkingLevel)) setThinkingLevel(levels[0] ?? 'off'); }} options={models.map((model) => ({ value: `${model.provider}/${model.id}`, label: model.name }))} /></label><label><span>推理强度</span><Select aria-label="角色默认推理强度" value={thinkingLevel} onValueChange={setThinkingLevel} options={thinkingLevels.map((level) => ({ value: level, label: thinkingLabel(level) }))} /></label><Button variant="primary" size="small" leadingIcon={<Save size={14} />} loading={saving} disabled={!changed || !modelProfile} onClick={() => void onSave(modelProfile, thinkingLevel)}>保存默认设置</Button></> : <p><BrainCircuit size={15} />当前 Pi 模型目录不可用，请先在配置页完成模型配置。</p>}</section></aside>;
}

type RoleBookProposal = {
  text: string;
  confidence: number;
  sourceEvidenceIds: string[];
};

type RoleBookDailyDraft = {
  draftId: string;
  createdAtMs: number;
  traitProposals: RoleBookProposal[];
  capabilityProposals: RoleBookProposal[];
  lessonProposals: RoleBookProposal[];
  commitmentProposals: RoleBookProposal[];
  decision: { decision?: string } | null;
};

type RoleBookActivationSelection = {
  roleId: string;
  roleVersion: string;
  revisionId: string;
  draftId: string;
  traitIndexes: number[];
  capabilityIndexes: number[];
  lessonIndexes: number[];
  commitmentIndexes: number[];
};

type RoleBookDiffItem = {
  itemId: string;
  text: string;
  evidenceIds: string[];
};

type RoleBookDiffSection = {
  section: string;
  label: string;
  added: RoleBookDiffItem[];
  removed: RoleBookDiffItem[];
  changed: Array<{
    itemId: string;
    before: RoleBookDiffItem;
    after: RoleBookDiffItem;
  }>;
};

function RoleBookInspector({ persona }: { persona: AgentPersonaV1 }) {
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
    <div className="role-inspector__hero"><PersonaAvatar persona={persona} size="hero" /><span><small>角色书</small><h3>{persona.displayName}</h3><p>{loading ? '正在读取…' : `Revision ${numberValue(activeRevision.revisionNumber) || 1}`}</p></span></div>
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
        <DialogHeader><DialogTitle>启用角色书修订</DialogTitle><DialogDescription>R1 确认 · 已核验 {numberValue(previewSummary.evidenceCount)} 条证据</DialogDescription></DialogHeader>
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

function TemplateInspector({ template }: { template: AgentTemplateV1 }) {
  return <aside className="role-inspector template-inspector"><div className="template-inspector__title"><span><Bot size={25} /></span><div><small>Agent 模板</small><h3>{template.displayName}</h3><p>{template.summary}</p></div></div><dl><div><dt><Wrench size={15} />工具范围</dt><dd>{toolBoundaryLabel(template.toolProfileVersion)}</dd></div><div><dt><Gauge size={15} />任务推进</dt><dd>按任务持续执行 · 可随时停止</dd></div><div><dt><LockKeyhole size={15} />任务上下文</dt><dd>{template.contextModes.map(contextModeLabel).join(' · ')}</dd></div></dl><div className="template-capabilities">{template.capabilities.map((capability) => <span key={capability}>{capabilityLabel(capability)}</span>)}</div></aside>;
}

function templateItems(value: unknown): AgentTemplateV1[] { const source = record(value); const items = Array.isArray(source.items) ? source.items : Array.isArray(source.templates) ? source.templates : []; return items.filter((item) => record(item).schemaVersion === 'rag-ime.agent-template.v1') as AgentTemplateV1[]; }
function createdSessionId(value: unknown): string { const session = record(record(value).session); return typeof session.id === 'string' ? session.id : ''; }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function arrayValue(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function textValue(value: unknown): string { return typeof value === 'string' ? value : ''; }
function numberValue(value: unknown): number { return typeof value === 'number' && Number.isFinite(value) ? value : 0; }
function ensureControlOk(value: unknown): Record<string, unknown> {
  const response = record(value);
  if (response.ok === false) throw new Error(textValue(response.error) || '操作未完成。');
  return response;
}
function toggleIndex(values: number[], index: number): number[] {
  return values.includes(index)
    ? values.filter((value) => value !== index)
    : [...values, index].sort((left, right) => left - right);
}
function roleBookProposals(value: unknown): RoleBookProposal[] {
  return arrayValue(value).flatMap((item) => {
    const proposal = record(item);
    const text = textValue(proposal.text);
    if (!text) return [];
    return [{
      text,
      confidence: Math.max(0, Math.min(1, numberValue(proposal.confidence))),
      sourceEvidenceIds: arrayValue(proposal.sourceEvidenceIds).map(textValue).filter(Boolean),
    }];
  });
}
function roleBookDailyDrafts(value: unknown): RoleBookDailyDraft[] {
  return arrayValue(record(value).dailyDrafts).flatMap((item) => {
    const draft = record(item);
    const draftId = textValue(draft.draftId);
    if (!draftId) return [];
    const decision = record(draft.decision);
    return [{
      draftId,
      createdAtMs: numberValue(draft.createdAtMs),
      traitProposals: roleBookProposals(draft.traitProposals),
      capabilityProposals: roleBookProposals(draft.capabilityProposals),
      lessonProposals: roleBookProposals(draft.lessonProposals),
      commitmentProposals: roleBookProposals(draft.commitmentProposals),
      decision: Object.keys(decision).length ? { decision: textValue(decision.decision) } : null,
    }];
  });
}
function roleBookHistory(value: unknown): Array<{ revisionId: string; revisionNumber: number; status: string; changeSummary: string }> {
  return arrayValue(record(value).history).flatMap((item) => {
    const revision = record(item);
    const revisionId = textValue(revision.revisionId);
    if (!revisionId) return [];
    return [{
      revisionId,
      revisionNumber: numberValue(revision.revisionNumber),
      status: textValue(revision.status),
      changeSummary: textValue(revision.changeSummary),
    }];
  });
}

function roleBookDiffItem(value: unknown): RoleBookDiffItem | null {
  const item = record(value);
  const itemId = textValue(item.itemId);
  const text = textValue(item.text);
  if (!itemId || !text) return null;
  return {
    itemId,
    text,
    evidenceIds: arrayValue(item.evidenceIds).map(textValue).filter(Boolean),
  };
}

function roleBookDiffSections(value: unknown): RoleBookDiffSection[] {
  return arrayValue(record(value).sections).flatMap((sectionValue) => {
    const section = record(sectionValue);
    const sectionId = textValue(section.section);
    const label = textValue(section.label);
    if (!sectionId || !label) return [];
    const added = arrayValue(section.added).flatMap((item) => {
      const parsed = roleBookDiffItem(item);
      return parsed ? [parsed] : [];
    });
    const removed = arrayValue(section.removed).flatMap((item) => {
      const parsed = roleBookDiffItem(item);
      return parsed ? [parsed] : [];
    });
    const changed = arrayValue(section.changed).flatMap((changeValue) => {
      const change = record(changeValue);
      const before = roleBookDiffItem(change.before);
      const after = roleBookDiffItem(change.after);
      const itemId = textValue(change.itemId);
      return before && after && itemId ? [{ itemId, before, after }] : [];
    });
    return [{ section: sectionId, label, added, removed, changed }];
  });
}

type RoleModel = AgentModelCatalogV1['providers'][number]['models'][number];
type RoleModelCatalog = { providers: Array<{ id: string; displayName: string; models: RoleModel[] }> };

function roleModelCatalog(value: unknown): RoleModelCatalog {
  const source = record(value);
  const providers = Array.isArray(source.providers) ? source.providers : [];
  return {
    providers: providers.flatMap((providerValue) => {
      const provider = record(providerValue);
      if (typeof provider.id !== 'string' || !Array.isArray(provider.models)) return [];
      const models = provider.models.filter((model): model is RoleModel => {
        const item = record(model);
        return typeof item.provider === 'string' && typeof item.id === 'string' && typeof item.name === 'string';
      });
      return [{ id: provider.id, displayName: typeof provider.displayName === 'string' ? provider.displayName : provider.id, models }];
    }),
  };
}

function thinkingLabel(level: string): string {
  return ({ off: '不启用推理', minimal: '最小', low: '低', medium: '中', high: '高', xhigh: '极高', max: 'Max' } as Record<string, string>)[level] ?? level;
}

function personaPhase(persona: AgentPersonaV1): { id: TimelineModel | ''; label: string } {
  const assetId = persona.visualProfile.avatarAssetId.toLowerCase();
  const policy = persona.defaults.modelPolicy.toLowerCase();
  if (assetId.includes('present') || policy.includes('terra')) return { id: 'terra', label: '此刻阶段' };
  if (assetId.includes('past') || policy.includes('luna')) return { id: 'luna', label: '初识阶段' };
  if (assetId.includes('future') || policy.includes('sol')) return { id: 'sol', label: '构筑阶段' };
  return { id: '', label: '自定义阶段' };
}

function personaExpressionTraits(persona: AgentPersonaV1): string[] {
  return persona.traits.filter((trait) => {
    const normalized = trait.trim().toLowerCase();
    return !/^(?:5\.6\s+)?(?:terra|luna|sol)$/.test(normalized);
  });
}

function normalizeTrait(value: string): string {
  return value.trim().replace(/\s+/gu, ' ').slice(0, 24);
}

function normalizedTraits(traits: readonly string[], pending = ''): string[] {
  const result: string[] = [];
  for (const candidate of [...traits, pending]) {
    const value = normalizeTrait(candidate);
    if (!value || result.some((item) => item.toLocaleLowerCase() === value.toLocaleLowerCase())) continue;
    result.push(value);
    if (result.length === 5) break;
  }
  return result;
}

function modeLabel(mode: AgentPersonaV1['selectableModes'][number]): string {
  return mode === 'assistant' ? '陪伴对话' : '协作主持';
}

function toolBoundaryLabel(value: AgentTemplateV1['toolProfileVersion']): string {
  return value === 'subagent-readonly-v1' ? '只读资料与审阅工具' : '受控执行工具';
}

function contextModeLabel(value: AgentTemplateV1['contextModes'][number]): string {
  return value === 'fresh' ? '独立上下文' : '继承当前上下文';
}

function capabilityLabel(value: AgentTemplateV1['capabilities'][number]): string {
  const labels: Record<AgentTemplateV1['capabilities'][number], string> = {
    rag: '知识检索',
    memory: '长期记忆',
    planning: '任务规划',
    review: '审阅',
    control: '受控操作',
    delegation: '任务委派',
  };
  return labels[value];
}
