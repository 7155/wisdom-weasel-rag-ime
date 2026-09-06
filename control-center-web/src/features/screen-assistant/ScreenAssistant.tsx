import { useEffect, useRef, useState } from 'react';
import { ExternalLink, Scan, Save } from 'lucide-react';
import { useControlTransport } from '@/app/control-transport';
import { publicAgentErrorText } from '@/features/agent/public-error';
import { useAgentLiveStore } from '@/features/agent/state/live-store';
import { PawSessionWorkspace } from '@/paw-os/apps/PawSessionWorkspace';
import '@/paw-os/styles/paw-os.css';
import '@/paw-os/apps/paw-apps.css';
import '@/paw-os/styles/paw-os-agent-migrated-v1.css';
import {
  latestCompletedScreenAnswer, prepareScreenConversation, screenActions, screenNoteBody,
  type CapturePreparation,
} from './screen-assistant-model';
import './screen-assistant.css';

export function ScreenAssistant() {
  const transport = useControlTransport();
  const state = useRef<CapturePreparation>({});
  const pending = useRef<ReturnType<typeof prepareScreenConversation> | null>(null);
  const [ready, setReady] = useState<Awaited<ReturnType<typeof prepareScreenConversation>>>();
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState('');
  const [draftRequest, setDraftRequest] = useState<{ id: number; text: string }>();
  const [saved, setSaved] = useState('');
  const [saving, setSaving] = useState(false);
  const answer = useAgentLiveStore((store) => latestCompletedScreenAnswer(ready ? store.projections[ready.session.id] : undefined));
  useEffect(() => {
    let current = true;
    const host = window.pawScreenAssistant;
    if (!host) { setError('请从 PAW 桌面应用或输入法菜单打开框选对话。'); return; }
    setError('');
    pending.current ??= prepareScreenConversation(transport, host, state.current);
    void pending.current.then((value) => { if (current) setReady(value); }).catch((reason) => {
      if (current) { pending.current = null; setError(publicAgentErrorText(reason)); }
    });
    return () => { current = false; };
  }, [transport, attempt]);

  async function saveNote() {
    if (!ready || !answer || saving) return;
    setSaving(true); setSaved(''); setError('');
    try {
      const receipt = await window.pawScreenAssistant!.saveNote({ body: screenNoteBody(answer, ready.capture, ready.session.id), sessionId: ready.session.id });
      if (receipt.saved) setSaved(`已保存：${receipt.name || '选区笔记.md'}`);
    } catch (reason) { setError(publicAgentErrorText(reason)); }
    finally { setSaving(false); }
  }

  return <main className="screen-assistant paw-desktop-root" data-app="agent">
    <header className="screen-assistant__header">
      <div><strong>选区对话</strong><span>围绕眼前的内容继续</span></div>
      <div className="screen-assistant__tools">
        <button aria-label="重新框选" title="重新框选，打开另一段对话" onClick={() => { void window.pawScreenAssistant?.capture().catch((reason) => setError(publicAgentErrorText(reason))); }}><Scan size={17} /></button>
        {ready && <button aria-label="在 PAW 中打开此会话" title="在 PAW 中打开此会话" onClick={() => { void window.pawScreenAssistant?.openSession(ready.session.id).catch((reason) => setError(publicAgentErrorText(reason))); }}><ExternalLink size={17} /></button>}
      </div>
    </header>
    {ready ? <>
      <details className="screen-assistant__source" open>
        <summary>本次选区 <span>{ready.capture.pixelWidth} × {ready.capture.pixelHeight}</span></summary>
        <img src={ready.capture.dataUrl} alt="本次框选的屏幕内容" />
      </details>
      <nav className="screen-assistant__actions" aria-label="选区任务">
        {screenActions.map((action) => <button key={action.id} onClick={() => { setDraftRequest({ id: Date.now(), text: action.draft }); setSaved(''); }}>{action.label}</button>)}
        <button disabled={!answer || saving} onClick={() => { void saveNote(); }}><Save size={14} />{saving ? '正在保存…' : '保存笔记'}</button>
      </nav>
      {saved && <p className="screen-assistant__notice" role="status">{saved}</p>}
      <section className="screen-assistant__conversation" aria-label="围绕选区对话">
        <PawSessionWorkspace key={ready.session.id} recordId={ready.session.id} record={ready.session}
          initialAttachments={ready.initialAttachments} draftRequest={draftRequest}
          screenContext={{ mediaId: ready.attachments[0].id, sourceAppBundleId: ready.capture.sourceAppBundleId, capturedAtMs: ready.capture.capturedAtMs }}
          appearance="embedded" showComposerControls composerPlaceholder="想了解这片选区的什么？也可以描述要完成的操作。"
          onNewWork={() => { void window.pawScreenAssistant?.capture(); }}
          onSessionCreated={(session) => { void window.pawScreenAssistant?.openSession(session.id); }}
          onSessionUpdated={(session) => {
            state.current.session = session;
            setReady((current) => current ? { ...current, session } : current);
            void window.pawScreenAssistant?.rememberConversation?.({ session }).catch((reason) => setError(publicAgentErrorText(reason)));
          }} />
      </section>
    </> : !error && <p className="screen-assistant__loading" role="status">正在把选区加入对话…</p>}
    {error && <div className="screen-assistant__error" role="alert"><p>{error}</p>{!ready && window.pawScreenAssistant && <button onClick={() => setAttempt((value) => value + 1)}>重试连接</button>}</div>}
  </main>;
}
