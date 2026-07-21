import { AtSign, Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { IconButton } from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';

interface ComposerParticipant {
  id: string;
  sessionId: string;
  roleId: string;
  roleVersion: string;
  displayName: string;
  collaborationRole?: 'coordinator' | 'executor' | 'researcher';
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
  addressedParticipantId,
  canSend,
  onDraftChange,
  onSend,
}: {
  room?: ComposerRoom;
  personas: AgentPersonaV1[];
  draft: string;
  addressedParticipantId: string;
  canSend: boolean;
  onDraftChange: (value: string) => void;
  onSend: () => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [mention, setMention] = useState<RoomMentionDraft>();
  const [activeIndex, setActiveIndex] = useState(0);
  const roomCanSend = room?.status === 'active';
  const participants = room?.participants.filter(
    (participant) => participant.status === 'active',
  ) ?? [];
  const mentionCandidates = mention
    ? participants.filter((participant) => roomMentionMatches(participant, mention.query))
    : [];

  useEffect(() => {
    setMention(undefined);
    setActiveIndex(0);
  }, [room?.id]);

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
      const suffix = draft.slice(currentMention.end).replace(/^ /, '');
      next = `${draft.slice(0, currentMention.start)}${inserted}${suffix}`;
      caret = currentMention.start + inserted.length;
    } else {
      const body = stripLeadingRoomMention(draft, participants);
      next = `@${participant.displayName}${body ? ` ${body}` : ' '}`;
      caret = `@${participant.displayName} `.length;
    }
    onDraftChange(next);
    setMention(undefined);
    setActiveIndex(0);
    queueMicrotask(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(caret, caret);
    });
  }

  function openMentionMenu(): void {
    const spacer = draft && !/\s$/u.test(draft) ? ' ' : '';
    const next = `${draft}${spacer}@`;
    const start = next.length - 1;
    onDraftChange(next);
    setMention({ start, end: next.length, query: '' });
    setActiveIndex(0);
    queueMicrotask(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(next.length, next.length);
    });
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
        {roomCanSend && participants.length ? <IconButton
          label="点名 Room 角色"
          icon={<AtSign size={16} />}
          aria-pressed={Boolean(addressedParticipantId)}
          onClick={openMentionMenu}
          tooltip
        /> : null}
        <textarea
          ref={textareaRef}
          rows={2}
          maxLength={8_000}
          value={draft}
          disabled={!roomCanSend}
          onChange={(event) => {
            onDraftChange(event.target.value);
            syncMention(event.target.value, event.target.selectionStart);
          }}
          onClick={(event) => (
            syncMention(event.currentTarget.value, event.currentTarget.selectionStart)
          )}
          onKeyUp={(event) => {
            if (!['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(event.key)) {
              syncMention(event.currentTarget.value, event.currentTarget.selectionStart);
            }
          }}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return;
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
              onSend();
            }
          }}
          placeholder={composerPlaceholder(room)}
          aria-label="Room 消息"
          aria-autocomplete="list"
          aria-controls={mention && mentionCandidates.length ? 'room-mention-menu' : undefined}
          aria-expanded={Boolean(mention && mentionCandidates.length)}
          aria-activedescendant={mention && mentionCandidates.length
            ? `room-mention-${mentionCandidates[activeIndex]?.id}`
            : undefined}
        />
        <IconButton
          label="发送 Room 消息"
          icon={<Send size={17} />}
          disabled={!canSend}
          onClick={onSend}
          tooltip
        />
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
  if (participant.collaborationRole === 'coordinator') return '主持协调';
  if (participant.collaborationRole === 'researcher') return '调研与核对';
  if (participant.collaborationRole === 'executor') return '执行与交付';
  return '协作角色';
}

function composerPlaceholder(room?: ComposerRoom): string {
  if (!room) return '先选择或新建 Room';
  if (room.status === 'archived') return '恢复 Room 后继续交流';
  return room.roomKind === 'roleplay'
    ? '向群聊发送消息，输入 @ 可点名…'
    : '向 Room 发消息，输入 @ 可点名…';
}
