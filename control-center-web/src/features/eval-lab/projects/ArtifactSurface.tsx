import { useEffect, useId, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button } from '@/components/primitives';
import { useRichHtmlUrl } from '@/features/agent/file-preview/use-rich-html-url';
import { object, type ArtifactAction, type ArtifactCode, type ArtifactForm, type ArtifactTable, type JsonValue, type LabArtifact } from './types';

export type ArtifactDraft = { revision: number; content: JsonValue; raw?: string };
const viewLabels = { markdown:'文档', table:'表格', form:'表单', code:'代码', html:'交互页面', json:'结构化数据' };
export function ArtifactSurface({ artifact, draft, busy, onDraft, onSave, onAction }: {
  artifact: LabArtifact; draft?: ArtifactDraft; busy: boolean;
  onDraft: (draft?: ArtifactDraft) => void;
  onSave: (content: JsonValue, revision: number) => Promise<boolean>;
  onAction: (action: ArtifactAction, values: Record<string, JsonValue>, staged?: boolean) => void;
}) {
  const [editing, setEditing] = useState(false); const [error, setError] = useState(''); const [showLatest, setShowLatest] = useState(false);
  const content = showLatest ? artifact.content : draft?.content ?? artifact.content;
  const revision = draft?.revision ?? artifact.revision;
  const changed = Boolean(draft); const stale = changed && revision !== artifact.revision;
  useEffect(() => { setEditing(false); setError(''); setShowLatest(false); }, [artifact.artifactId]);
  const valueText = draft?.raw ?? (typeof content === 'string' ? content : JSON.stringify(content, null, 2));
  const update = (next: JsonValue, raw?: string) => { setError(''); onDraft({ revision, content: next, ...(raw !== undefined ? { raw } : {}) }); };
  const save = async () => {
    let next = content;
    if (draft?.raw !== undefined && !['markdown', 'html'].includes(artifact.view)) {
      try { next = JSON.parse(valueText) as JsonValue; } catch { setError('JSON 格式还不完整，草稿已保留。'); return; }
    }
    if (await onSave(next, revision)) { onDraft(undefined); setEditing(false); setError(''); }
  };
  const actionValues = artifact.view === 'form' ? (content as unknown as ArtifactForm).values : {};
  return <section className="lab-artifact" aria-label={artifact.title}>
    <header className="lab-artifact__header">
      <div><small>{viewLabels[artifact.view]} · v{artifact.revision}</small><h2>{artifact.title}</h2>{artifact.summary ? <p>{artifact.summary}</p> : null}</div>
      <div className="lab-artifact__toolbar">
        {artifact.view !== 'form' ? <Button size="small" disabled={busy || showLatest} onClick={() => setEditing((value) => !value)}>{editing ? '查看成果' : '编辑内容'}</Button> : null}
        {changed ? <Button size="small" disabled={busy} onClick={() => { onDraft(undefined); setError(''); }}>放弃本地修改</Button> : null}
        {changed ? <Button size="small" variant="primary" disabled={busy || stale} onClick={() => void save()}>保存新版本</Button> : null}
      </div>
    </header>
    {stale ? <div className="lab-project-notice" role="status"><strong>成果已有新版本，你的草稿仍在。</strong><p>可以先查看新版，再决定要保留的内容。</p><Button size="small" onClick={() => { setShowLatest((value) => !value); setEditing(false); }}>{showLatest ? '返回我的草稿' : '查看新版，保留草稿'}</Button><Button size="small" onClick={() => { onDraft({ ...draft!, revision: artifact.revision }); setShowLatest(false); }}>用草稿作为新版内容</Button></div> : null}
    {error ? <p className="lab-project-error" role="alert">{error}</p> : null}
    <div className={`lab-artifact__content lab-artifact__content--${artifact.view}`}>
      {editing ? <textarea className="lab-artifact__source" aria-label="成果内容草稿" spellCheck={false} value={valueText} readOnly={busy}
        onChange={(event) => update(['markdown', 'html'].includes(artifact.view) ? event.target.value : content, event.target.value)} />
        : artifact.view === 'markdown' ? <div className="lab-artifact__markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{String(content)}</ReactMarkdown></div>
          : artifact.view === 'html' ? <IsolatedProjectHtml artifact={artifact} content={String(content)} onAction={(action, values) => { if (!changed) onAction(action, values, true); }} />
            : artifact.view === 'table' ? <ProjectTable content={content as unknown as ArtifactTable} />
              : artifact.view === 'form' ? <ProjectForm content={content as unknown as ArtifactForm} disabled={busy || showLatest} onChange={(next) => update(next as unknown as JsonValue)} />
                : artifact.view === 'code' ? <ProjectCode content={content as unknown as ArtifactCode} />
                  : <pre className="lab-artifact__json">{JSON.stringify(content, null, 2)}</pre>}
    </div>
    {artifact.actions.length ? <footer className="lab-artifact__actions">{artifact.actions.map((action) => <Button key={action.actionId} disabled={busy || changed} onClick={() => {
      const form = artifact.view === 'form' ? content as unknown as ArtifactForm : undefined;
      const missing = form?.fields.find((field) => field.required && (form.values[field.key] === undefined || form.values[field.key] === null || form.values[field.key] === '' || Array.isArray(form.values[field.key]) && (form.values[field.key] as JsonValue[]).length === 0));
      if (missing) { setError(`请填写“${missing.label}”，再继续。`); return; }
      onAction(action, actionValues);
    }}>{action.label}</Button>)}{changed ? <span>先保存输入，再继续此成果的操作。</span> : null}</footer> : null}
    {artifact.templateRef ? <p className="lab-artifact__provenance">模板引用：{artifact.templateRef.skillId} / {artifact.templateRef.templateId} · {artifact.templateRef.version}</p> : null}
  </section>;
}

function ProjectTable({ content }: { content: ArtifactTable }) {
  return <div className="lab-artifact__table-scroll"><table>{content.caption ? <caption>{content.caption}</caption> : null}
    <thead><tr>{content.columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead>
    <tbody>{content.rows.length ? content.rows.map((row, index) => <tr key={index}>{content.columns.map((column) => <td key={column.key}>{formatValue(row[column.key])}</td>)}</tr>)
      : <tr><td colSpan={content.columns.length}>当前还没有记录。</td></tr>}</tbody>
  </table></div>;
}
function formatValue(value: JsonValue | undefined): string {
  return value === null || value === undefined ? '—' : typeof value === 'string' ? value : typeof value === 'object' ? JSON.stringify(value) : String(value);
}
function ProjectCode({ content }: { content: ArtifactCode }) {
  return <div className="lab-artifact__code">{content.filename ? <p>{content.filename}</p> : null}<pre><code>{content.source}</code></pre></div>;
}
function ProjectForm({ content, disabled, onChange }: { content: ArtifactForm; disabled: boolean; onChange: (value: ArtifactForm) => void }) {
  const id = useId();
  const update = (key: string, value: JsonValue) => onChange({ ...content, values: { ...content.values, [key]: value } });
  return <div className="lab-artifact__form">{content.description ? <p>{content.description}</p> : null}{content.fields.map((field, index) => {
    const fieldId = `${id}-${index}`; const value = content.values[field.key];
    return <div className="lab-artifact__field" key={field.key}>
      <label htmlFor={fieldId}>{field.label}{field.required ? <span aria-label="必填"> *</span> : null}</label>
      {field.description ? <p id={`${fieldId}-help`}>{field.description}</p> : null}
      {field.type === 'boolean' ? <input id={fieldId} type="checkbox" disabled={disabled} checked={value === true} onChange={(event) => update(field.key, event.target.checked)} />
        : field.type === 'long_text' ? <textarea id={fieldId} disabled={disabled} rows={5} placeholder={field.placeholder} value={typeof value === 'string' ? value : ''} onChange={(event) => update(field.key, event.target.value)} />
          : field.type === 'select' || field.type === 'multiselect' ? <select id={fieldId} disabled={disabled} multiple={field.type === 'multiselect'} value={field.type === 'multiselect' ? (Array.isArray(value) ? value.map(String) : []) : typeof value === 'string' ? value : ''}
            onChange={(event) => update(field.key, field.type === 'multiselect' ? [...event.currentTarget.selectedOptions].map((option) => option.value) : event.target.value)}>
            {field.type === 'select' ? <option value="">请选择</option> : null}{field.options?.map((option) => <option key={option} value={option}>{option}</option>)}</select>
            : <input id={fieldId} disabled={disabled} type={field.type === 'number' ? 'number' : 'text'} placeholder={field.placeholder} value={typeof value === 'number' || typeof value === 'string' ? value : ''}
              onChange={(event) => update(field.key, field.type === 'number' ? event.target.value === '' ? null : Number(event.target.value) : event.target.value)} />}
    </div>;
  })}</div>;
}

/** Unique-origin HTML can only stage declared user interaction, never call a Tool. */
function IsolatedProjectHtml({ artifact, content, onAction }: { artifact: LabArtifact; content: string; onAction: (action: ArtifactAction, values: Record<string, JsonValue>) => void }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const source = useMemo(() => isolatedProjectDocument(content), [content]);
  const previewUrl = useRichHtmlUrl(source);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow) return;
      const message = object(event.data);
      if (message.type !== 'paw.lab.artifact.action' || typeof message.actionId !== 'string') return;
      const action = artifact.actions.find((item) => item.actionId === message.actionId);
      if (!action) return;
      const values = object(message.values);
      try { if (JSON.stringify(values).length > 16000) return; } catch { return; }
      onAction(action, values as Record<string, JsonValue>);
    };
    window.addEventListener('message', receive); return () => window.removeEventListener('message', receive);
  }, [artifact.actions, onAction]);
  return <iframe ref={frame} title={artifact.title} sandbox="allow-scripts" referrerPolicy="no-referrer" src={previewUrl} />;
}
export function isolatedProjectDocument(content: string): string {
  const csp = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
  // The policy is parsed before any project-authored markup. A later meta tag
  // can only add restrictions. No allow-same-origin, navigation or popups.
  return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${csp}"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>${content}</body></html>`;
}
