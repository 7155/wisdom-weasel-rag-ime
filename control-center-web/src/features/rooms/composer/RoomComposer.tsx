import { AtSign, Send } from 'lucide-react';
import {
  startTransition,
  useEffect,
  useRef,
  useState,
  type CompositionEvent,
} from 'react';

import { IconButton } from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';

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
  personas,
  draft,
  sending,
  onDraftChange,
  onSend,
}: {
  room?: ComposerRoom;
  personas: AgentPersonaV1[];
  draft: string;
  sending: boolean;
  onDraftChange: (value: string) => void;
  onSend: (value: string) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composingRef = useRef(false);
  const [composerDraft, setComposerDraft] = useState(draft);
  const [mention, setMention] = useState<RoomMentionDraft>();
  const [activeIndex, setActiveIndex] = useState(0);
  const roomCanSend = room?.status === 'active';
  const participants = room?.participants.filter(
    (participant) => participant.status === 'active',
  ) ?? [];
  const mentionCandidates = mention
    ? participants.filter((participant) => roomMentionMatches(participant, mention.query))
    : [];
  const addressedParticipantId = roomMentionedParticipants(
    participants,
    composerDraft,
  )[0]?.id ?? '';
  const canSend = Boolean(roomCanSend && composerDraft.trim() && !sending);

  useEffect(() => {
    setComposerDraft(draft);
    setMention(undefined);
    setActiveIndex(0);
  }, [draft]);

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
    setMention(activeRoomMention(value, caret ?? value.length));
    setActiveIndex(0);
  }

  function chooseParticipant(
    participant: ComposerParticipant,
    currentMention = mention,
  ): void {
    let next: string;
    let caret: number;
    if (currentMention) {
      const inserted = `@${participant.displayName} `;
      const suffix = composerDraft.slice(currentMention.end).replace(/^ /, '');
      next = `${composerDraft.slice(0, currentMention.start)}${inserted}${suffix}`;
      caret = currentMention.start + inserted.length;
    } else {
      const body = stripLeadingRoomMention(composerDraft, participants);
      next = `@${participant.displayName}${body ? ` ${body}` : ' '}`;
      caret = `@${participant.displayName} `.length;
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

  function submit(): void {
    if (!canSend) return;
    const value = composerDraft;
    setComposerDraft('');
    setMention(undefined);
    setActiveIndex(0);
    publishDraft('');
    onSend(value);
  }

  return <div className="room-composer-shell">
    <div className="room-composer-wrap">
      {mention && mentionCandidates.length ? <div
        id="room-mention-menu"
        className="room-mention-menu"
        role="listbox"
        aria-label="选择 Room 角色"
      >
        <header><AtSign size={14} /><span><strong>点名角色</strong><small>继续输入可筛选</small></span></header>
        {mentionCandidates.map((participant, index) => <button
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
          <PersonaAvatar
            persona={personas.find((item) => (
              item.roleId === participant.roleId
              && item.version === participant.roleVersion
            ))}
            size="small"
          />
          <span><strong>{participant.displayName}</strong><small>{participantRoleLabel(participant)}</small></span>
          <kbd>{index === activeIndex ? 'Enter' : `@${participant.displayName}`}</kbd>
        </button>)}
      </div> : null}
      <div className="room-composer">
        <textarea
          ref={textareaRef}
          rows={1}
          maxLength={8_000}
          value={composerDraft}
          disabled={!roomCanSend}
          autoCapitalize="none"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
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
          placeholder={composerPlaceholder(room)}
          aria-label="Room 消息"
          aria-autocomplete="list"
          aria-controls={mention && mentionCandidates.length ? 'room-mention-menu' : undefined}
          aria-activedescendant={mention && mentionCandidates.length
            ? `room-mention-${mentionCandidates[activeIndex]?.id}`
            : undefined}
        />
        <div className="room-composer__toolbar">
          <div className="room-composer__controls">
            {roomCanSend && participants.length ? <IconButton
              className="room-composer__mention"
              label="点名 Room 角色"
              icon={<AtSign size={16} />}
              aria-pressed={Boolean(addressedParticipantId)}
              onClick={openMentionMenu}
              tooltip
            /> : null}
          </div>
          <IconButton
            className="room-composer__send"
            label="发送 Room 消息"
            icon={<Send size={17} />}
            disabled={!canSend}
            onClick={submit}
            tooltip
          />
        </div>
      </div>
    </div>
  </div>;
}

export function roomMentionedParticipants<T extends ComposerParticipant>(
  participants: T[],
  value: string,
): T[] {
  const matched: T[] = [];
  for (const participant of participants) {
    const token = `@${participant.displayName}`;
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

function roomMentionMatches(participant: ComposerParticipant, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  return participant.displayName.toLocaleLowerCase().includes(needle)
    || participant.roleId.toLocaleLowerCase().includes(needle);
}

function stripLeadingRoomMention(
  value: string,
  participants: ComposerParticipant[],
): string {
  const body = value.trimStart();
  for (const participant of participants) {
    const token = `@${participant.displayName}`;
    if (body.startsWith(token)) return body.slice(token.length).trimStart();
  }
  return body;
}

function participantRoleLabel(participant: ComposerParticipant): string {
  if (participant.collaborationRole === 'coordinator') return '协作主持';
  if (participant.collaborationRole === 'researcher') return '调研与核对';
  if (participant.collaborationRole === 'implementer') return '实施与交付';
  if (participant.collaborationRole === 'reviewer') return '独立验收';
  if (participant.collaborationRole === 'specialist') return '领域专家';
  return '协作角色';
}

function composerPlaceholder(room?: ComposerRoom): string {
  if (!room) return '先选择或新建 Room';
  if (room.status === 'archived') return '恢复 Room 后继续交流';
  return room.roomKind === 'roleplay'
    ? '向群聊发送消息，输入 @ 可点名…'
    : '向 Room 发消息，输入 @ 可点名…';
}
