import { useEffect, useState, type FormEvent } from 'react';

import { useControlTransport } from '@/app/control-transport';
import {
  agentCommandReceiptFailure,
  isAmbiguousAgentPromptFailure,
} from '@/features/agent/public-error';
import { sessionItems, type SessionSummary } from '@/features/agent/types';
import { PawSessionWorkspace } from '@/paw-os/apps/PawSessionWorkspace';
import type { PawExtensionAppProps } from '@/paw-os/extensions/types';
import {
  createPendingAppMessage,
  promptRequestFor,
  successorForDurablyFailedCommand,
  type PendingAppMessage,
} from './message-identity';
import './app.css';

const MODES = [
  {
    id: 'overview',
    label: 'Overview',
    purpose: 'Answer from current authoritative evidence and expose missing sources.',
    placeholder: 'Ask for an evidence-backed overview',
  },
  {
    id: 'review',
    label: 'Review',
    purpose: 'Compare claims, show disagreements, and retain unresolved items.',
    placeholder: 'Ask to compare or review current evidence',
  },
] as const;

type ModeId = (typeof MODES)[number]['id'];

export default function ExtensionAppFrontend({ manifest }: PawExtensionAppProps) {
  const transport = useControlTransport();
  const [modeId, setModeId] = useState<ModeId>('overview');
  const [sessions, setSessions] = useState<Partial<Record<ModeId, SessionSummary>>>({});
  const [drafts, setDrafts] = useState<Record<ModeId, string>>({ overview: '', review: '' });
  const [pending, setPending] = useState<Partial<Record<ModeId, PendingAppMessage>>>({});
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const mode = MODES.find((item) => item.id === modeId)!;
  const session = sessions[modeId];
  const pendingMessage = pending[modeId];

  useEffect(() => {
    let active = true;
    void transport.request({
      pathId: 'agent.sessions.list',
      query: {
        limit: 100,
        includeArchived: false,
        surfaceKind: 'extension_app',
        ownerAppId: manifest.id,
      },
    }).then((value) => {
      if (!active) return;
      const restored: Partial<Record<ModeId, SessionSummary>> = {};
      for (const candidate of sessionItems(value, { includeAppOwned: true })) {
        if (candidate.surfaceKind !== 'extension_app' || candidate.ownerAppId !== manifest.id) continue;
        if (!MODES.some((item) => item.id === candidate.surfaceKey) || restored[candidate.surfaceKey as ModeId]) continue;
        restored[candidate.surfaceKey as ModeId] = candidate;
      }
      setSessions(restored);
      setError('');
    }).catch((reason) => {
      if (active) setError(publicError(reason, 'The App conversation could not be restored.'));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [manifest.id, transport]);

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    const userMessage = drafts[modeId].trim();
    if (!userMessage || sending || pendingMessage) return;
    setSending(true);
    setError('');
    try {
      const created = await transport.request<Record<string, unknown>>({
        pathId: 'agent.sessions.create',
        body: {
          title: `${manifest.label} · ${mode.label}`,
          mode: 'assistant',
          toolProfileVersion: 'control-center-v1',
          executionMode: 'per_action',
          workspaceRoots: [],
          surfaceKind: 'extension_app',
          ownerAppId: manifest.id,
          surfaceKey: modeId,
        },
      });
      const raw = record(record(created).session);
      const sessionId = text(raw.id);
      if (!sessionId) throw new Error('Runtime did not return a Session id.');
      await transport.request({
        pathId: 'agent.session.mode.update',
        params: { sessionId },
        body: {
          mode: 'assistant',
          executionMode: 'per_action',
          toolProfileVersion: 'control-center-v1',
          projectContextEnabled: false,
          piSkillsEnabled: true,
          codexSkillsEnabled: false,
        },
      });
      const summary = sessionSummary(raw, sessionId, manifest.id, modeId, manifest.label);
      const logicalMessage = createPendingAppMessage({
        sessionId,
        ownerAppId: manifest.id,
        surfaceKey: modeId,
        message: firstTurnContract(manifest.skillRef, mode, userMessage),
      });
      setSessions((current) => ({ ...current, [modeId]: summary }));
      setPending((current) => ({ ...current, [modeId]: logicalMessage }));
      await sendLogicalMessage(logicalMessage).catch((reason) => {
        retainSafeRetry(logicalMessage, reason);
        throw reason;
      });
      setPending((current) => ({ ...current, [modeId]: undefined }));
      setDrafts((current) => ({ ...current, [modeId]: '' }));
    } catch (reason) {
      setError(publicError(reason, 'The message was not confirmed. Retry keeps the same message identity.'));
    } finally {
      setSending(false);
    }
  }

  async function retry(): Promise<void> {
    if (!pendingMessage || sending) return;
    setSending(true);
    setError('');
    try {
      await sendLogicalMessage(pendingMessage).catch((reason) => {
        retainSafeRetry(pendingMessage, reason);
        throw reason;
      });
      setPending((current) => ({ ...current, [modeId]: undefined }));
      setDrafts((current) => ({ ...current, [modeId]: '' }));
    } catch (reason) {
      setError(publicError(reason, 'Retry was not confirmed; the logical message remains pending.'));
    } finally {
      setSending(false);
    }
  }

  async function sendLogicalMessage(logicalMessage: PendingAppMessage): Promise<void> {
    await transport.request(promptRequestFor(logicalMessage));
  }

  function retainSafeRetry(logicalMessage: PendingAppMessage, reason: unknown): void {
    const receipt = agentCommandReceiptFailure(reason);
    const retry = receipt?.state === 'failed' && receipt.clientMessageId === logicalMessage.clientMessageId
      ? successorForDurablyFailedCommand(logicalMessage)
      : isAmbiguousAgentPromptFailure(reason)
        ? logicalMessage
        : undefined;
    setPending((current) => ({ ...current, [modeId]: retry }));
  }

  function newConversation(): void {
    setSessions((current) => ({ ...current, [modeId]: undefined }));
    setPending((current) => ({ ...current, [modeId]: undefined }));
    setError('');
  }

  return (
    <main className="extension-app-template">
      <header>
        <span><small>Extension App</small><h1>{manifest.label}</h1></span>
        <span aria-label={`Manifest version ${manifest.version}`} className="extension-app-template__version">v{manifest.version}</span>
      </header>

      <nav aria-label={`${manifest.label} modes`} role="tablist">
        {MODES.map((item) => (
          <button
            aria-controls={`mode-panel-${item.id}`}
            aria-selected={item.id === modeId}
            id={`mode-tab-${item.id}`}
            key={item.id}
            onClick={() => setModeId(item.id)}
            role="tab"
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>

      {error ? <p className="extension-app-template__error" role="alert">{error}</p> : null}
      {pendingMessage ? (
        <div className="extension-app-template__retry" role="status">
          <span>This logical message is pending confirmation.</span>
          <button disabled={sending} onClick={() => void retry()} type="button">Retry</button>
          <button disabled={sending} onClick={() => setPending((current) => ({ ...current, [modeId]: undefined }))} type="button">Discard</button>
        </div>
      ) : null}

      <section
        aria-labelledby={`mode-tab-${modeId}`}
        id={`mode-panel-${modeId}`}
        role="tabpanel"
      >
        {loading ? <p role="status">Restoring App conversation…</p> : session ? (
          <PawSessionWorkspace
            active
            appearance="embedded"
            composerPlaceholder={`${mode.placeholder}, or continue the conversation`}
            onNewWork={newConversation}
            onSessionCreated={(created) => setSessions((current) => ({ ...current, [modeId]: created }))}
            onSessionUpdated={(updated) => setSessions((current) => ({ ...current, [modeId]: updated }))}
            record={session}
            recordId={session.id}
          />
        ) : (
          <form onSubmit={(event) => void submit(event)}>
            <div><h2>{mode.label}</h2><p>{mode.purpose}</p></div>
            <label htmlFor={`message-${modeId}`}>Start this App conversation</label>
            <textarea
              id={`message-${modeId}`}
              onChange={(event) => setDrafts((current) => ({ ...current, [modeId]: event.target.value }))}
              placeholder={mode.placeholder}
              rows={4}
              value={drafts[modeId]}
            />
            <button disabled={sending || !drafts[modeId].trim()} type="submit">{sending ? 'Starting…' : 'Start'}</button>
          </form>
        )}
      </section>
    </main>
  );
}

function firstTurnContract(skillRef: string, mode: (typeof MODES)[number], userMessage: string): string {
  return [
    `Use the installed App Skill: ${skillRef}.`,
    `App mode: ${mode.label}. ${mode.purpose}`,
    'Use only authoritative sources available to this Session and state missing evidence explicitly.',
    '',
    `User request: ${userMessage}`,
  ].join('\n');
}

function sessionSummary(
  raw: Record<string, unknown>,
  id: string,
  ownerAppId: string,
  surfaceKey: ModeId,
  label: string,
): SessionSummary {
  return {
    id,
    title: text(raw.title) || `${label} · ${surfaceKey}`,
    mode: text(raw.mode) || 'assistant',
    status: text(raw.status) || 'running',
    roleId: text(raw.roleId),
    roleVersion: text(raw.roleVersion),
    roleBookRevisionId: text(raw.roleBookRevisionId),
    updatedAtMs: typeof raw.updatedAtMs === 'number' ? raw.updatedAtMs : Date.now(),
    workspaceRoots: [],
    executionMode: 'per_action',
    piSkillsEnabled: true,
    surfaceKind: 'extension_app',
    ownerAppId,
    surfaceKey,
  } as SessionSummary;
}

function publicError(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message.trim() ? reason.message : fallback;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
