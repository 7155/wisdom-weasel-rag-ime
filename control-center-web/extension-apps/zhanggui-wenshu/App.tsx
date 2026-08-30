import { ArrowUpRight, BarChart3, CircleAlert, FolderOpen, LoaderCircle, PackageOpen, Send } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';

import { useControlTransport } from '@/app/control-transport';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import { sessionItems, type SessionSummary } from '@/features/agent/types';
import { PawSessionWorkspace } from '@/paw-os/apps/PawSessionWorkspace';
import { PawAppIcon } from '@/paw-os/shell/PawAppIcon';
import type { PawExtensionAppProps } from '@/paw-os/extensions/types';
import './app.css';

const MODES = [
  {
    id: 'ask',
    label: '问数',
    eyebrow: '经营问答',
    title: '直接问经营数据',
    description: '先定位口径和来源，再给数值、时间范围与证据。',
    placeholder: '例如：北斗项目一季度销售额是多少？',
    suggestions: ['本月销售额和上月相比怎样？', '哪些项目贡献了主要收入？'],
  },
  {
    id: 'reconcile',
    label: '对账',
    eyebrow: '差异核对',
    title: '把两个口径放在一起核对',
    description: '列出差异、来源、时间窗和仍需补充的数据，不静默抹平冲突。',
    placeholder: '例如：核对销售台账与回款表的季度差异',
    suggestions: ['检查订单金额与回款金额差异', '找出两份报表口径不一致的项目'],
  },
  {
    id: 'explain',
    label: '解释',
    eyebrow: '指标说明',
    title: '把数字为什么变化讲清楚',
    description: '把计算口径、影响因素和证据拆开，不把估计值说成事实。',
    placeholder: '例如：解释本月毛利率下降的主要原因',
    suggestions: ['解释收入增长但现金回款下降', '说明这个指标的计算口径'],
  },
] as const;

type ModeId = (typeof MODES)[number]['id'];

export default function ZhangguiWenshuApp({ manifest }: PawExtensionAppProps) {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const [modeId, setModeId] = useState<ModeId>('ask');
  const [sessions, setSessions] = useState<Partial<Record<ModeId, SessionSummary>>>({});
  const [draft, setDraft] = useState('');
  const [workspaceRoot, setWorkspaceRoot] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const activeMode = MODES.find((mode) => mode.id === modeId)!;
  const activeSession = sessions[modeId];
  const sessionIds = useMemo(() => readSessionIds(manifest.id), [manifest.id]);
  const liveSessionIds = useRef(sessionIds);

  useEffect(() => {
    let active = true;
    void transport.request({ pathId: 'agent.sessions.list', query: { limit: 100, includeArchived: false } })
      .then((value) => {
        if (!active) return;
        const listed = new Map(sessionItems(value).map((session) => [session.id, session]));
        const restored = Object.fromEntries(MODES.flatMap((mode) => {
          const session = listed.get(liveSessionIds.current[mode.id] ?? '');
          return session ? [[mode.id, session]] : [];
        })) as Partial<Record<ModeId, SessionSummary>>;
        setSessions(restored);
        persistSessionIds(manifest.id, restored);
        setError('');
      })
      .catch((reason) => {
        if (active) setError(publicError(reason, '没有读到掌柜问数的对话记录。'));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [manifest.id, transport]);

  async function startConversation(message: string): Promise<void> {
    const userMessage = message.trim();
    if (!userMessage || sending) return;
    setSending(true);
    setError('');
    try {
      const created = await transport.request<Record<string, unknown>>({
        pathId: 'agent.sessions.create',
        body: {
          title: `${manifest.label} · ${activeMode.label}`,
          mode: workspaceRoot ? 'coordinator' : 'assistant',
          toolProfileVersion: 'control-center-v1',
          executionMode: 'per_action',
          workspaceRoots: workspaceRoot ? [workspaceRoot] : [],
        },
      });
      const raw = record(record(created).session);
      const sessionId = text(raw.id);
      if (!sessionId) throw new Error('服务端没有返回可验证的 Session。');
      await transport.request({
        pathId: 'agent.session.mode.update',
        params: { sessionId },
        body: {
          mode: workspaceRoot ? 'coordinator' : 'assistant',
          executionMode: 'per_action',
          toolProfileVersion: 'control-center-v1',
          projectContextEnabled: false,
          piSkillsEnabled: true,
          codexSkillsEnabled: false,
        },
      });
      const session = sessionSummary(raw, sessionId, `${manifest.label} · ${activeMode.label}`, userMessage, workspaceRoot);
      const next = { ...sessions, [modeId]: session };
      setSessions(next);
      liveSessionIds.current = Object.fromEntries(Object.entries(next).map(([key, value]) => [key, value?.id])) as Partial<Record<ModeId, string>>;
      persistSessionIds(manifest.id, next);
      setDraft('');
      await transport.request({
        pathId: 'agent.session.prompt',
        params: { sessionId },
        body: {
          message: bootstrapPrompt(manifest.skillRef, activeMode, userMessage, workspaceRoot),
          clientMessageId: `extension:${manifest.id}:${modeId}:${Date.now()}`,
          delivery: 'prompt',
        },
      });
    } catch (reason) {
      setError(publicError(reason, '掌柜问数没有开始，请重试。'));
    } finally {
      setSending(false);
    }
  }

  async function pickDataWorkspace(): Promise<void> {
    if (!transport.pickFiles) {
      setError('当前运行环境不能选择数据工作目录。');
      return;
    }
    try {
      const selection = await transport.pickFiles({
        purpose: 'workspace-root',
        selection: 'directory',
        multiple: false,
        maxFiles: 1,
      });
      const path = selection[0]?.path?.trim() ?? '';
      if (path) {
        setWorkspaceRoot(path);
        setError('');
      }
    } catch (reason) {
      setError(publicError(reason, '数据目录没有选中。'));
    }
  }

  function resetMode(): void {
    const next = { ...sessions };
    delete next[modeId];
    setSessions(next);
    liveSessionIds.current = Object.fromEntries(Object.entries(next).map(([key, value]) => [key, value?.id])) as Partial<Record<ModeId, string>>;
    persistSessionIds(manifest.id, next);
    setDraft('');
  }

  return (
    <main className="zhanggui-app" data-mode={modeId}>
      <header className="zhanggui-app__header">
        <span className="zhanggui-app__identity">
          <PawAppIcon appId={manifest.id} size={34} />
          <span><small>{activeMode.eyebrow}</small><h1>{manifest.label}</h1></span>
        </span>
        <span className="zhanggui-app__header-actions">
          <span className="zhanggui-app__suite">SGG · {manifest.verticalSuiteRevision}</span>
          <button onClick={() => openPawOsRoute(desktop, `/plugins?packageId=${encodeURIComponent(manifest.packageId)}`)} type="button"><PackageOpen size={15} />管理与卸载</button>
          {activeSession ? <button onClick={() => openPawOsRoute(desktop, `/agent?session=${encodeURIComponent(activeSession.id)}`)} type="button">完整 Session<ArrowUpRight size={14} /></button> : null}
        </span>
      </header>

      <nav aria-label="掌柜问数模式" className="zhanggui-app__modes" role="tablist">
        {MODES.map((mode) => (
          <button
            aria-label={mode.label}
            aria-selected={mode.id === modeId}
            key={mode.id}
            onClick={() => { setModeId(mode.id); setDraft(''); setError(''); }}
            role="tab"
            type="button"
          >
            <span>{mode.label}</span>
            <small>{mode.eyebrow}</small>
          </button>
        ))}
      </nav>

      {error ? <p className="zhanggui-app__error" role="alert"><CircleAlert size={15} />{error}</p> : null}
      {loading ? <div className="zhanggui-app__loading" role="status"><LoaderCircle className="ui-spin" size={18} />正在恢复问数记录…</div> : activeSession ? (
        <section className="zhanggui-app__session" aria-label={`${activeMode.label}对话`}>
          <div className="zhanggui-app__session-note">
            <span><strong>{activeMode.label}</strong>{activeMode.description}</span>
            <button onClick={resetMode} type="button">新建本模式对话</button>
          </div>
          <PawSessionWorkspace
            active
            onNewWork={resetMode}
            onSessionCreated={(session) => {
              const next = { ...sessions, [modeId]: session };
              setSessions(next);
              persistSessionIds(manifest.id, next);
            }}
            onSessionUpdated={(session) => {
              setSessions((current) => {
                const next = { ...current, [modeId]: session };
                persistSessionIds(manifest.id, next);
                return next;
              });
            }}
            record={activeSession}
            recordId={activeSession.id}
          />
        </section>
      ) : (
        <section className="zhanggui-app__start">
          <span className="zhanggui-app__mark"><BarChart3 size={24} /></span>
          <div className="zhanggui-app__start-copy"><small>{activeMode.eyebrow}</small><h2>{activeMode.title}</h2><p>{activeMode.description}</p></div>
          <div className="zhanggui-app__suggestions">
            {activeMode.suggestions.map((suggestion) => <button key={suggestion} onClick={() => setDraft(suggestion)} type="button">{suggestion}</button>)}
          </div>
          <div className="zhanggui-app__source">
            <button onClick={() => void pickDataWorkspace()} type="button"><FolderOpen size={15} />{workspaceRoot ? '更换数据目录' : '选择数据目录'}</button>
            <span>{workspaceRoot ? workspaceRoot.split(/[\\/]/).filter(Boolean).at(-1) : '可选；不选择时只使用当前 Session 已授权的 Knowledge / Tool 来源'}</span>
          </div>
          <form onSubmit={(event) => { event.preventDefault(); void startConversation(draft); }}>
            <textarea aria-label={`${activeMode.label}问题`} onChange={(event) => setDraft(event.target.value)} placeholder={activeMode.placeholder} rows={3} value={draft} />
            <button aria-label={sending ? '正在创建对话' : '发送'} disabled={sending || !draft.trim()} type="submit">
              {sending ? <LoaderCircle className="ui-spin" size={16} /> : <Send size={16} />}
            </button>
          </form>
          <p>使用普通 Pi Session 与专属 {manifest.skillRef} Skill；SGG 仅用于沙盒自测，不会冒充真实经营数据。</p>
        </section>
      )}
    </main>
  );
}

function bootstrapPrompt(skillRef: string, mode: (typeof MODES)[number], userMessage: string, workspaceRoot: string): string {
  return [
    `请加载并严格遵循 \`${skillRef}\` Skill。`,
    `当前掌柜问数模式：${mode.label}（${mode.eyebrow}）。`,
    mode.description,
    '只使用当前 Session 中真实可访问的来源；缺少来源时明确指出，不要用 SGG fixture 代替真实经营数据。',
    workspaceRoot ? `用户已显式绑定数据工作目录：${workspaceRoot}` : '用户未绑定数据工作目录；不得假定本机存在某个数据库或项目。',
    '',
    `用户请求：${userMessage}`,
  ].join('\n');
}

function sessionSummary(raw: Record<string, unknown>, id: string, title: string, preview: string, workspaceRoot: string): SessionSummary {
  return {
    id,
    title: text(raw.title) || title,
    mode: text(raw.mode) || (workspaceRoot ? 'coordinator' : 'assistant'),
    status: text(raw.status) || 'running',
    roleId: text(raw.roleId),
    roleVersion: text(raw.roleVersion),
    roleBookRevisionId: text(raw.roleBookRevisionId),
    updatedAtMs: typeof raw.updatedAtMs === 'number' ? raw.updatedAtMs : Date.now(),
    workspaceRoots: workspaceRoot ? [workspaceRoot] : [],
    lastMessagePreview: preview,
    executionMode: 'per_action',
    piSkillsEnabled: true,
  } as SessionSummary;
}

function storageKey(appId: string): string {
  return `pawos.extension-app.sessions.v1:${appId}`;
}

function readSessionIds(appId: string): Partial<Record<ModeId, string>> {
  try {
    const raw = window.localStorage.getItem(storageKey(appId));
    const value = raw ? JSON.parse(raw) : {};
    if (!isRecord(value)) return {};
    return Object.fromEntries(MODES.flatMap((mode) => typeof value[mode.id] === 'string' ? [[mode.id, value[mode.id]]] : []));
  } catch {
    return {};
  }
}

function persistSessionIds(appId: string, sessions: Partial<Record<ModeId, SessionSummary>>): void {
  const ids = Object.fromEntries(Object.entries(sessions).flatMap(([modeId, session]) => session?.id ? [[modeId, session.id]] : []));
  try {
    window.localStorage.setItem(storageKey(appId), JSON.stringify(ids));
  } catch {
    // Session ownership stays in Pi. Losing this convenience index only means
    // the App starts a new mode conversation after reload.
  }
}

function record(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function publicError(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message ? reason.message : fallback;
}
