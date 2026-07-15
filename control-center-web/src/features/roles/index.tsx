import {
  Bot,
  Gauge,
  LockKeyhole,
  MessageCirclePlus,
  Plus,
  ShieldCheck,
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
  SegmentedControl,
} from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { AgentTemplateV1 } from '@/contracts/generated/agent-template.v1';
import { previewPersonas, previewTemplates } from '@/features/agent/preview-data';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { roleItems } from '@/features/agent/types';
import { publicErrorText } from '@/features/overview/management-ui';
import './roles.css';

export function RolesFeature() {
  const transport = useControlTransport();
  const navigate = useNavigate();
  const [view, setView] = useState<'personas' | 'templates'>('personas');
  const [personas, setPersonas] = useState<AgentPersonaV1[]>(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas : []);
  const [templates, setTemplates] = useState<AgentTemplateV1[]>(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewTemplates : []);
  const [selectedPersona, setSelectedPersona] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas[0]?.roleId ?? '' : '');
  const [selectedTemplate, setSelectedTemplate] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewTemplates[0]?.templateId ?? '' : '');
  const [sessionCreating, setSessionCreating] = useState(false);
  const [roleCreating, setRoleCreating] = useState(false);
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
    ]).then(([roleResult, templateResult]) => {
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

  const pendingTraits = normalizedTraits(createTraits, traitDraft);

  return <>
    <main className="roles-feature" data-route-id="roles">
      <header className="roles-header"><span><h2>角色与 Agent 模板</h2><p>角色决定陪伴方式，模板决定任务能力</p></span><SegmentedControl aria-label="角色视图" value={view} onValueChange={(value) => setView(value as 'personas' | 'templates')} items={[{ value: 'personas', label: '角色' }, { value: 'templates', label: 'Agent 模板' }]} />{view === 'personas' ? <div className="roles-header-actions"><IconButton label="创建角色" icon={<UserRoundPlus size={16} />} onClick={beginRoleCreation} tooltip /><Button variant="primary" size="small" disabled={!persona} loading={sessionCreating} leadingIcon={<MessageCirclePlus size={15} />} onClick={() => void startPersonaSession()}>开始对话</Button></div> : null}</header>
      {notice ? <p className="roles-notice" role="status">{notice}</p> : null}
      {view === 'personas' ? (
        <div className="roles-layout">
          <section className="persona-grid" aria-label="角色列表">{personas.length ? personas.map((item) => <button type="button" key={`${item.roleId}:${item.version}`} data-accent={item.visualProfile.accentToken} aria-current={item.roleId === selectedPersona} onClick={() => { setSelectedPersona(item.roleId); setActionNotice(''); }}><PersonaAvatar persona={item} size="large" /><span><strong>{item.displayName}</strong><small>{item.tagline}</small></span><div><b aria-label="角色阶段">{personaPhase(item).label}</b>{personaExpressionTraits(item).map((trait) => <i key={trait}>{trait}</i>)}</div></button>) : <p className="roles-empty">本机还没有可用角色。</p>}</section>
          {persona ? <PersonaInspector persona={persona} /> : null}
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

function PersonaInspector({ persona }: { persona: AgentPersonaV1 }) {
  const phase = personaPhase(persona);
  const expressionTraits = personaExpressionTraits(persona);
  return <aside className="role-inspector" data-accent={persona.visualProfile.accentToken}><div className="role-inspector__hero"><PersonaAvatar persona={persona} size="hero" /><span><small>角色</small><h3>{persona.displayName}</h3><p>{persona.summary}</p></span></div><dl><div><dt><Gauge size={15} />陪伴阶段</dt><dd>{phase.label}</dd></div><div><dt><Sparkles size={15} />表达特征</dt><dd>{expressionTraits.length ? expressionTraits.join(' · ') : '自然'}</dd></div><div><dt><LockKeyhole size={15} />可用方式</dt><dd>{persona.selectableModes.map(modeLabel).join(' · ')}</dd></div><div><dt><ShieldCheck size={15} />操作确认</dt><dd>敏感操作由你确认</dd></div><div><dt><Wrench size={15} />工具使用</dt><dd>按任务调用已连接工具</dd></div></dl></aside>;
}

function TemplateInspector({ template }: { template: AgentTemplateV1 }) {
  return <aside className="role-inspector template-inspector"><div className="template-inspector__title"><span><Bot size={25} /></span><div><small>Agent 模板</small><h3>{template.displayName}</h3><p>{template.summary}</p></div></div><dl><div><dt><Wrench size={15} />工具范围</dt><dd>{toolBoundaryLabel(template.toolProfileVersion)}</dd></div><div><dt><Gauge size={15} />任务额度</dt><dd>最多 {template.budget.maxTurns} 轮 · 最多 {template.budget.maxToolCalls} 次工具使用</dd></div><div><dt><LockKeyhole size={15} />任务上下文</dt><dd>{template.contextModes.map(contextModeLabel).join(' · ')}</dd></div></dl><div className="template-capabilities">{template.capabilities.map((capability) => <span key={capability}>{capabilityLabel(capability)}</span>)}</div></aside>;
}

function templateItems(value: unknown): AgentTemplateV1[] { const source = record(value); const items = Array.isArray(source.items) ? source.items : Array.isArray(source.templates) ? source.templates : []; return items.filter((item) => record(item).schemaVersion === 'rag-ime.agent-template.v1') as AgentTemplateV1[]; }
function createdSessionId(value: unknown): string { const session = record(record(value).session); return typeof session.id === 'string' ? session.id : ''; }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }

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
