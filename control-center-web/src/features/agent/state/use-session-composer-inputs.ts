import { useEffect, useRef, useState } from 'react';
import type { ComposerAttachment } from '../types';

type SessionComposerInput = {
  draft: string;
  attachments: ComposerAttachment[];
};

type SessionComposerInputsOptions = {
  selectedSessionId: string;
  getSelectedSessionId: () => string;
};

type DraftStoreRegistry = typeof globalThis & {
  __RAG_DRAFT_STORES__?: Array<{ clear(): void }>;
};

/* Session composer inputs survive route unmount: module scope, not a ref. */
const sessionComposerStore = new Map<string, SessionComposerInput>();
const draftStoreRegistry = globalThis as DraftStoreRegistry;
(draftStoreRegistry.__RAG_DRAFT_STORES__ ??= []).push(sessionComposerStore);

export function useSessionComposerInputs({
  selectedSessionId,
  getSelectedSessionId,
}: SessionComposerInputsOptions) {
  const composerInputsRef = useRef(sessionComposerStore);
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);

  function inputForSession(sessionId: string): SessionComposerInput {
    return composerInputsRef.current.get(sessionId) ?? { draft: '', attachments: [] };
  }

  function setSessionDraft(
    sessionId: string,
    value: string | ((current: string) => string),
  ): void {
    if (!sessionId) return;
    const current = inputForSession(sessionId);
    const nextDraft = typeof value === 'function' ? value(current.draft) : value;
    composerInputsRef.current.set(sessionId, { ...current, draft: nextDraft });
    if (getSelectedSessionId() === sessionId) setDraft(nextDraft);
  }

  function setSessionAttachments(
    sessionId: string,
    value: ComposerAttachment[] | ((current: ComposerAttachment[]) => ComposerAttachment[]),
  ): void {
    if (!sessionId) return;
    const current = inputForSession(sessionId);
    const nextAttachments = typeof value === 'function'
      ? value(current.attachments)
      : value;
    composerInputsRef.current.set(sessionId, { ...current, attachments: nextAttachments });
    if (getSelectedSessionId() === sessionId) setAttachments(nextAttachments);
  }

  function restoreSessionInputIfUntouched(
    sessionId: string,
    nextDraft: string,
    nextAttachments: ComposerAttachment[],
  ): boolean {
    const current = inputForSession(sessionId);
    if (current.draft || current.attachments.length > 0) return false;
    composerInputsRef.current.set(sessionId, { draft: nextDraft, attachments: nextAttachments });
    if (getSelectedSessionId() === sessionId) {
      setDraft(nextDraft);
      setAttachments(nextAttachments);
    }
    return true;
  }

  function setSelectedDraft(value: string | ((current: string) => string)): void {
    setSessionDraft(getSelectedSessionId(), value);
  }

  function persistSelectedDraft(value: string): void {
    const sessionId = getSelectedSessionId();
    if (!sessionId) return;
    const current = inputForSession(sessionId);
    composerInputsRef.current.set(sessionId, { ...current, draft: value });
  }

  function setSelectedAttachments(
    value: ComposerAttachment[] | ((current: ComposerAttachment[]) => ComposerAttachment[]),
  ): void {
    setSessionAttachments(getSelectedSessionId(), value);
  }

  function mergeSessionAttachments(
    sessionId: string,
    files: Omit<ComposerAttachment, 'source'>[],
    source: ComposerAttachment['source'],
  ): void {
    setSessionAttachments(sessionId, (current) => {
      const byId = new Map(current.map((item) => [item.id, item]));
      for (const file of files) byId.set(file.id, { ...file, source });
      return [...byId.values()].slice(0, 8);
    });
  }

  function seedSessionInput(
    sessionId: string,
    nextDraft: string,
    nextAttachments: ComposerAttachment[],
  ): void {
    composerInputsRef.current.set(sessionId, { draft: nextDraft, attachments: nextAttachments });
  }

  function deleteSessionInput(sessionId: string): void {
    composerInputsRef.current.delete(sessionId);
  }

  useEffect(() => {
    const input = inputForSession(selectedSessionId);
    setDraft(input.draft);
    setAttachments(input.attachments);
  }, [selectedSessionId]);

  return {
    draft,
    attachments,
    setSessionDraft,
    setSessionAttachments,
    setSelectedDraft,
    persistSelectedDraft,
    setSelectedAttachments,
    restoreSessionInputIfUntouched,
    mergeSessionAttachments,
    seedSessionInput,
    deleteSessionInput,
  };
}
