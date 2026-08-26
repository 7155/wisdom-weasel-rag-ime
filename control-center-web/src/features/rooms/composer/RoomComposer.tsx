import { AtSign, ListPlus, Plus, Send } from 'lucide-react';
import {
  startTransition,
  useCallback,
  useEffect,
  useRef,
  useState,
  type CompositionEvent,
  type ClipboardEvent,
} from 'react';

import { IconButton } from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { RoomAttachmentReceipt } from '@/contracts/room-reducer';
import { ComposerShell } from '@/features/composer/ComposerShell';
import { roomCollaborationRoleLabel } from '../room-copy';

interface ComposerParticipant {
  id: string;
  sessionId: string;
  roleId: string;
  roleVersion: string;
  displayName: string;
  collaborationRole?: 'coordinator' | 'researcher' | 'implementer' | 'reviewer' | 'specialist';
  status: string;
}

interface ComposerRoom {
  id: string;
  status: string;
  roomKind?: 'collaboration' | 'roleplay';
  participants: ComposerParticipant[];
}

interface RoomMentionDraft {
  start: number;
  end: number;
  query: string;
}

export function RoomComposer({
  room,
  participantAliases = {},
  personas: _personas,
  draft,
  attachments,
  sending,
  taskBusyState,
  pendingUserAnswer = false,
  inputRef,
  queueDepth = 0,
  onDraftChange,
  onQueue,
  onSend,
  onAttachmentsChange,
  onPasteImages,
  onPasteFromClipboard,
  onPickAttachments,
}: {
  room?: ComposerRoom;
  participantAliases?: Readonly<Record<string, string>>;
  personas: AgentPersonaV1[];
  draft: string;
  attachments: RoomAttachmentReceipt[];
  sending: boolean;
  taskBusyState?: 'running' | 'blocked';
  pendingUserAnswer?: boolean;
  inputRef?: { current: HTMLTextAreaElement | null };
  /** How many follow-ups the host is already holding for this Room. */
  queueDepth?: number;
  /** Hold this draft until the running turn settles. Returns false when the
   *  queue cap refused it, in which case the text stays in the composer. */
  onQueue?: (value: string) => boolean;
  onDraftChange: (value: string) => void;
  onAttachmentsChange: (value: RoomAttachmentReceipt[]) => void;
  onPasteImages: (files: File[]) => void;
  onPasteFromClipboard: () => void;
  onPickAttachments: () => void;
  onSend: (value: string) => void | boolean | Promise<boolean>;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composingRef = useRef(false);
  const setTextareaRef = useCallback((node: HTMLTextAreaElement | null) => {
    textareaRef.current = node;
    if (inputRef) inputRef.current = node;
  }, [inputRef]);
  const [composerDraft, setComposerDraft] = useState(draft);
  const [mention, setMention] = useState<RoomMentionDraft>();
  const [activeIndex, setActiveIndex] = useState(0);
  const roomCanCompose = room?.status === 'active';
  const pendingAnswerMode = Boolean(pendingUserAnswer);
  const roomCanSend = roomCanCompose;
  const participants = room?.participants.filter(
    (participant) => participant.status === 'active',
  ) ?? [];
  const mentionCandidates = mention
    ? participants.filter((participant) => roomMentionMatches(participant, mention.query, participantAliases))
    : [];
  const canSend = Boolean(
    roomCanSend
    && (pendingAnswerMode ? composerDraft.trim() : composerDraft.trim() || attachments.length)
    && !sending,
  );
  /* Queueing is offered only where it is the real alternative to steering: a
     running turn, plain text, and no question waiting on this answer. */
  const canQueue = Boolean(
    onQueue && taskBusyState === 'running' && !pendingAnswerMode && composerDraft.trim() && !sending,
  );

  useEffect(() => {
    setComposerDraft(draft);
    setMention(undefined);
    setActiveIndex(0);
  }, [draft]);

  useEffect(() => {
    if (!pendingAnswerMode) return;
    setMention(undefined);
    setActiveIndex(0);
  }, [pendingAnswerMode]);

  function publishDraft(value: string): void {
    startTransition(() => onDraftChange(value));
  }

  function endComposition(event: CompositionEvent<HTMLTextAreaElement>): void {
    const value = event.currentTarget.value;
    composingRef.current = false;
    setComposerDraft(value);
    publishDraft(value);
    syncMention(value, event.currentTarget.selectionStart);
  }

  function syncMention(value: string, caret: number | null): void {
    if (pendingAnswerMode) {
      setMention(undefined);
      return;
    }
    setMention(activeRoomMention(value, caret ?? value.length));
    setActiveIndex(0);
  }

  function chooseParticipant(
    participant: ComposerParticipant,
    currentMention = mention,
  ): void {
    let next: string;
    let caret: number;
    const mentionName = roomParticipantMentionName(participant, participantAliases);
    if (currentMention) {
      const inserted = `@${mentionName} `;
      const suffix = composerDraft.slice(currentMention.end).replace(/^ /, '');
      next = `${composerDraft.slice(0, currentMention.start)}${inserted}${suffix}`;
      caret = currentMention.start + inserted.length;
    } else {
      const body = stripLeadingRoomMention(composerDraft, participants, participantAliases);
      next = `@${mentionName}${body ? ` ${body}` : ' '}`;
      caret = `@${mentionName} `.length;
    }
    setComposerDraft(next);
    publishDraft(next);
    setMention(undefined);
    setActiveIndex(0);
    queueMicrotask(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(caret, caret);
    });
  }

  function openMentionMenu(): void {
    const spacer = composerDraft && !/\s$/u.test(composerDraft) ? ' ' : '';
    const next = `${composerDraft}${spacer}@`;
    const start = next.length - 1;
    setComposerDraft(next);
    publishDraft(next);
    setMention({ start, end: next.length, query: '' });
    setActiveIndex(0);
    queueMicrotask(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(next.length, next.length);
    });
  }

  function paste(event: ClipboardEvent<HTMLTextAreaElement>): void {
    // Any pasted file — image, PDF, code, archive — rides the managed
    // attachment path; plain text keeps the browser's default insertion.
    const files = [...event.clipboardData.files];
    let hasFileItem = files.length > 0;
    if (!files.length) {
      for (const item of event.clipboardData.items ?? []) {
        if (item.kind !== 'file') continue;
        hasFileItem = true;
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (!files.length && !hasFileItem) {
      const text = event.clipboardData.getData?.('text/plain') ?? '';
      if (text) return;
      event.preventDefault();
      onPasteFromClipboard();
      return;
    }
    event.preventDefault();
    if (files.length) onPasteImages(files);
    else onPasteFromClipboard();
  }

  function clearDraft(): void {
    setComposerDraft('');
    setMention(undefined);
    setActiveIndex(0);
    publishDraft('');
  }

  function submit(): void {
    if (!canSend) return;
    const value = composerDraft;
    const result = onSend(value);
    const restoreDraft = () => {
      setComposerDraft(value);
      setMention(undefined);
      setActiveIndex(0);
      publishDraft(value);
    };
    if (result === false) {
      restoreDraft();
      return;
    }
    clearDraft();
    if (result && typeof result !== 'boolean') {
      void result.then((accepted) => {
        if (accepted === false) restoreDraft();
      });
    }
  }

  /* Queueing never reaches Runtime, so a refused draft must stay visible and
     editable rather than vanish into a full queue. */
  function queueDraft(): void {
    if (!canQueue || !onQueue) return;
    if (onQueue(composerDraft)) clearDraft();
  }

  return <div className="room-composer-shell">
    <div className="room-composer-wrap">
      {mention && mentionCandidates.length ? <div
        id="room-mention-menu"
        className="room-mention-menu"
        role="listbox"
        aria-label="选择要点名的伙伴"
      >
        <header><AtSign size={14} /><span><strong>想请谁加入</strong><small>继续输入名字可以筛选</small></span></header>
        {mentionCandidates.map((participant, index) => {
          const mentionName = roomParticipantMentionName(participant, participantAliases);
          const secondary = roomCollaborationRoleLabel(participant.collaborationRole);
          return <button
          type="button"
          id={`room-mention-${participant.id}`}
          role="option"
          aria-selected={index === activeIndex}
          key={participant.id}
          onMouseDown={(event) => {
            event.preventDefault();
            chooseParticipant(participant);
          }}
        >
          <span aria-hidden="true" className="room-mention-menu__marker"><AtSign size={14} /></span>
          <span><strong>{mentionName}</strong><small>{secondary}</small></span>
          <kbd>{index === activeIndex ? 'Enter' : `@${mentionName}`}</kbd>
        </button>;
        })}
      </div> : null}
      <ComposerShell
        surface="room"
        className="room-composer"
        onSurfacePress={() => textareaRef.current?.focus()}
        banner={taskBusyState || pendingAnswerMode ? (
          <p className="room-composer__task-lock" role="status">
            {pendingAnswerMode
              ? '当前任务正在等待你的回答。这里只发送文字回答；点名和附件不会随回答发送。'
              : taskBusyState === 'blocked'
                ? '当前任务已暂停。发送文字可以告诉主持伙伴怎样继续，停止按钮会终止整条协作。'
                : '当前任务仍在执行。现在发送文字会立即干预主持伙伴的当前回合。'}
          </p>
        ) : undefined}
        attachments={attachments.map((attachment) => ({
          id: attachment.mediaId,
          name: attachment.fileName,
          mimeType: attachment.mimeType,
          byteSize: attachment.byteSize,
          sha256: attachment.sha256,
          roomId: attachment.roomId,
        }))}
        onRemoveAttachment={(id) => onAttachmentsChange(
          attachments.filter((item) => item.mediaId !== id),
        )}
        textarea={(
          <textarea
            ref={setTextareaRef}
            rows={1}
            maxLength={8_000}
            value={composerDraft}
            disabled={!roomCanCompose}
            autoCapitalize="none"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            onPaste={paste}
            onChange={(event) => {
              setComposerDraft(event.target.value);
              if (!composingRef.current) publishDraft(event.target.value);
              syncMention(event.target.value, event.target.selectionStart);
            }}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={endComposition}
            onClick={(event) => (
              syncMention(event.currentTarget.value, event.currentTarget.selectionStart)
            )}
            onKeyUp={(event) => {
              if (!['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(event.key)) {
                syncMention(event.currentTarget.value, event.currentTarget.selectionStart);
              }
            }}
            onKeyDown={(event) => {
              if (
                composingRef.current
                || event.nativeEvent.isComposing
                || event.nativeEvent.keyCode === 229
              ) return;
              if (mention && mentionCandidates.length) {
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                  event.preventDefault();
                  setActiveIndex((current) => (
                    current
                    + (event.key === 'ArrowDown' ? 1 : -1)
                    + mentionCandidates.length
                  ) % mentionCandidates.length);
                  return;
                }
                if (event.key === 'Enter' || event.key === 'Tab') {
                  event.preventDefault();
                  chooseParticipant(mentionCandidates[activeIndex] ?? mentionCandidates[0]);
                  return;
                }
                if (event.key === 'Escape') {
                  event.preventDefault();
                  setMention(undefined);
                  return;
                }
              }
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder={pendingAnswerMode
              ? '回答伙伴正在等待的问题…'
              : taskBusyState
                ? '立即干预当前回合…'
                : composerPlaceholder(room)}
            aria-label="协作消息"
            aria-autocomplete="list"
            aria-controls={mention && mentionCandidates.length ? 'room-mention-menu' : undefined}
            aria-activedescendant={mention && mentionCandidates.length
              ? `room-mention-${mentionCandidates[activeIndex]?.id}`
              : undefined}
          />
        )}
        controls={(
          <>
            <IconButton
              className="agent-composer__attachment room-composer__attachment"
              label="添加附件"
              icon={<Plus size={18} />}
              disabled={!roomCanCompose || sending || pendingAnswerMode || Boolean(taskBusyState) || attachments.length >= 8}
              onClick={onPickAttachments}
              tooltip
            />
            {roomCanCompose && participants.length && !pendingAnswerMode ? <IconButton
              className="room-composer__mention"
              label="点名一位伙伴"
              icon={<AtSign size={16} />}
              aria-controls={mention && mentionCandidates.length ? 'room-mention-menu' : undefined}
              aria-expanded={Boolean(mention && mentionCandidates.length)}
              aria-haspopup="listbox"
              onClick={openMentionMenu}
              tooltip
            /> : null}
          </>
        )}
        actions={(
          <>
            {onQueue && taskBusyState === 'running' && !pendingAnswerMode ? <IconButton
              className="room-composer__queue"
              label={queueDepth ? `排到当前回合之后（已排 ${queueDepth} 条）` : '排到当前回合之后'}
              icon={<ListPlus size={18} />}
              disabled={!canQueue}
              onClick={queueDraft}
              tooltip
            /> : null}
          <IconButton
            className="agent-composer__send room-composer__send"
            label={pendingAnswerMode
              ? '发送问题回答'
              : taskBusyState === 'blocked'
                ? '告诉伙伴怎样继续'
                : taskBusyState
                  ? '立即干预当前回合'
                  : '发送消息'}
            icon={<Send size={18} />}
            disabled={!canSend}
            onClick={submit}
            tooltip
          />
          </>
        )}
      />
    </div>
  </div>;
}

export function roomMentionedParticipants<T extends ComposerParticipant>(
  participants: T[],
  value: string,
  participantAliases: Readonly<Record<string, string>> = {},
): T[] {
  const matched: T[] = [];
  for (const participant of participants) {
    for (const name of roomParticipantMentionNames(participant, participantAliases)) {
      const token = `@${name}`;
      let offset = value.indexOf(token);
      while (offset >= 0) {
        const previous = offset > 0 ? value[offset - 1] : '';
        const next = value[offset + token.length] ?? '';
        const startsAtBoundary = !previous || /[\s([{（【「『，。！？、,:：；;]/u.test(previous);
        const endsAtBoundary = !next || /[\s)\]}）】」』，。！？、,.!?:：；;]/u.test(next);
        if (startsAtBoundary && endsAtBoundary) {
          matched.push(participant);
          break;
        }
        offset = value.indexOf(token, offset + token.length);
      }
      if (matched.at(-1) === participant) break;
    }
  }
  return matched;
}

function activeRoomMention(value: string, caret: number): RoomMentionDraft | undefined {
  const boundedCaret = Math.max(0, Math.min(caret, value.length));
  const beforeCaret = value.slice(0, boundedCaret);
  const start = beforeCaret.lastIndexOf('@');
  if (start < 0) return undefined;
  const previous = start > 0 ? value[start - 1] : '';
  if (previous && !/[\s([{（【「『，。！？、,:：；;]/u.test(previous)) return undefined;
  const query = value.slice(start + 1, boundedCaret);
  if (query.length > 80 || /\s/u.test(query)) return undefined;
  return { start, end: boundedCaret, query };
}

function roomMentionMatches(
  participant: ComposerParticipant,
  query: string,
  participantAliases: Readonly<Record<string, string>>,
): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  return roomParticipantMentionNames(participant, participantAliases)
    .some((name) => name.toLocaleLowerCase().includes(needle))
    || participant.roleId.toLocaleLowerCase().includes(needle);
}

function stripLeadingRoomMention(
  value: string,
  participants: ComposerParticipant[],
  participantAliases: Readonly<Record<string, string>>,
): string {
  const body = value.trimStart();
  for (const participant of participants) {
    for (const name of roomParticipantMentionNames(participant, participantAliases)) {
      const token = `@${name}`;
      if (body.startsWith(token)) return body.slice(token.length).trimStart();
    }
  }
  return body;
}

function roomParticipantMentionName(
  participant: ComposerParticipant,
  participantAliases: Readonly<Record<string, string>>,
): string {
  return participantAliases[participant.id]?.trim() || participant.displayName;
}

function roomParticipantMentionNames(
  participant: ComposerParticipant,
  participantAliases: Readonly<Record<string, string>>,
): string[] {
  const preferred = roomParticipantMentionName(participant, participantAliases);
  return preferred === participant.displayName ? [preferred] : [preferred, participant.displayName];
}

function composerPlaceholder(room?: ComposerRoom): string {
  if (!room) return '选择一个协作空间，或新建一个';
  if (room.status === 'archived') return '恢复这个协作空间后就能继续聊';
  return room.roomKind === 'roleplay'
    ? '说点什么；输入 @ 可以请一位伙伴回应'
    : '继续聊，或输入 @ 请一位伙伴接手';
}
