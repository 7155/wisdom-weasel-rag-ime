import { Bot, Gauge, LockKeyhole, MessageCirclePlus, ShieldCheck, Sparkles, Wrench } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import { Button, SegmentedControl } from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { AgentTemplateV1 } from '@/contracts/generated/agent-template.v1';
import { previewPersonas, previewTemplates } from '@/features/agent/preview-data';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { roleItems } from '@/features/agent/types';
import './roles.css';

export function RolesFeature() {
  const transport = useControlTransport();
  const navigate = useNavigate();
  const [view, setView] = useState<'personas' | 'templates'>('personas');
  const [personas, setPersonas] = useState<AgentPersonaV1[]>(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas : []);
  const [templates, setTemplates] = useState<AgentTemplateV1[]>(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewTemplates : []);
  const [selectedPersona, setSelectedPersona] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas[0]?.roleId ?? '' : '');
  const [selectedTemplate, setSelectedTemplate] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewTemplates[0]?.templateId ?? '' : '');
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let active = true;
    void Promise.all([
      transport.request({ pathId: 'agent.roles.list' }),
      transport.request({ pathId: 'agent.subagents.templates' }),
    ]).then(([roleResponse, templateResponse]) => {
      if (!active) return;
      const roles = roleItems(roleResponse);
      const values = templateItems(templateResponse);
      if (roles.length) { setPersonas(roles); setSelectedPersona((current) => current || roles[0]?.roleId || ''); }
      if (values.length) { setTemplates(values); setSelectedTemplate((current) => current || values[0]?.templateId || ''); }
    }).catch((error) => active && setNotice(error instanceof Error ? error.message : String(error)));
    return () => { active = false; };
  }, [transport]);
  const persona = personas.find((item) => item.roleId === selectedPersona);
  const template = templates.find((item) => item.templateId === selectedTemplate);

  async function startPersonaSession(): Promise<void> {
    if (!persona || creating) return;
    setCreating(true);
    setNotice('');
    try {
      const response = await transport.request({
        pathId: 'agent.sessions.create',
        body: {
          title: `${persona.displayName} 对话`,
          mode: 'assistant',
          roleId: persona.roleId,
          roleVersion: persona.version,
          modelProfile: persona.defaults.modelPolicy,
          toolProfileVersion: persona.defaults.toolProfileVersion,
          workspaceRoots: [],
        },
      });
      const sessionId = createdSessionId(response);
      if (!sessionId) throw new Error('创建 Session 失败，请重试。');
      navigate(`/agent?session=${encodeURIComponent(sessionId)}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className="roles-feature" data-route-id="roles">
      <header className="roles-header"><span><h2>角色与 Agent 模板</h2><p>说话者视觉与运行权限保持独立</p></span><SegmentedControl aria-label="角色视图" value={view} onValueChange={(value) => setView(value as 'personas' | 'templates')} items={[{ value: 'personas', label: 'Persona' }, { value: 'templates', label: 'Agent Template' }]} />{view === 'personas' ? <Button variant="primary" size="small" loading={creating} leadingIcon={<MessageCirclePlus size={15} />} onClick={() => void startPersonaSession()}>开始对话</Button> : null}</header>
      {notice ? <p className="roles-notice" role="status">{notice}</p> : null}
      {view === 'personas' ? (
        <div className="roles-layout">
          <section className="persona-grid" aria-label="Persona 列表">{personas.length ? personas.map((item) => <button type="button" key={item.roleId} data-accent={item.visualProfile.accentToken} aria-current={item.roleId === selectedPersona} onClick={() => { setSelectedPersona(item.roleId); setNotice(''); }}><PersonaAvatar persona={item} size="large" /><span><strong>{item.displayName}</strong><small>{item.tagline}</small></span><div>{item.traits.map((trait) => <i key={trait}>{trait}</i>)}</div></button>) : <p className="roles-empty">尚未从本机 Agent Kernel 读取到角色。</p>}</section>
          {persona ? <PersonaInspector persona={persona} /> : null}
        </div>
      ) : (
        <div className="roles-layout">
          <section className="template-list" aria-label="Agent Template 列表">{templates.length ? templates.map((item) => <button type="button" key={item.templateId} aria-current={item.templateId === selectedTemplate} onClick={() => setSelectedTemplate(item.templateId)}><span><Bot size={17} /></span><div><strong>{item.displayName}</strong><small>{item.summary}</small></div></button>) : <p className="roles-empty">尚未从本机 Agent Kernel 读取到模板。</p>}</section>
          {template ? <TemplateInspector template={template} /> : null}
        </div>
      )}
    </main>
  );
}

function PersonaInspector({ persona }: { persona: AgentPersonaV1 }) {
  return <aside className="role-inspector" data-accent={persona.visualProfile.accentToken}><div className="role-inspector__hero"><PersonaAvatar persona={persona} size="hero" /><span><small>PERSONA</small><h3>{persona.displayName}</h3><p>{persona.summary}</p></span></div><dl><div><dt><Sparkles size={15} />表达特征</dt><dd>{persona.traits.join(' · ')}</dd></div><div><dt><ShieldCheck size={15} />安全策略</dt><dd>{persona.safetyPolicyVersion}</dd></div><div><dt><LockKeyhole size={15} />可选模式</dt><dd>{persona.selectableModes.map((mode) => mode === 'assistant' ? '受控模式' : '运行协调').join(' · ')}</dd></div><div><dt><Wrench size={15} />工具配置</dt><dd>{persona.defaults.toolProfileVersion}</dd></div></dl></aside>;
}

function TemplateInspector({ template }: { template: AgentTemplateV1 }) {
  return <aside className="role-inspector template-inspector"><div className="template-inspector__title"><span><Bot size={25} /></span><div><small>AGENT TEMPLATE</small><h3>{template.displayName}</h3><p>{template.summary}</p></div></div><dl><div><dt><Wrench size={15} />工具边界</dt><dd>{template.toolProfileVersion}</dd></div><div><dt><Gauge size={15} />预算</dt><dd>{template.budget.maxTurns} turns · {template.budget.maxToolCalls} tools · {Math.round(template.budget.maxTotalTokens / 1_000)}k tokens</dd></div><div><dt><LockKeyhole size={15} />上下文</dt><dd>{template.contextModes.join(' · ')}</dd></div></dl><div className="template-capabilities">{template.capabilities.map((capability) => <span key={capability}>{capability}</span>)}</div></aside>;
}

function templateItems(value: unknown): AgentTemplateV1[] { const source = record(value); const items = Array.isArray(source.items) ? source.items : Array.isArray(source.templates) ? source.templates : []; return items.filter((item) => record(item).schemaVersion === 'rag-ime.agent-template.v1') as AgentTemplateV1[]; }
function createdSessionId(value: unknown): string { const session = record(record(value).session); return typeof session.id === 'string' ? session.id : ''; }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
