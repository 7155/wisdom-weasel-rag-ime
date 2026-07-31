import type { QuestionOption, RoomPostV2 } from '@/contracts/generated/room-post.v2';
import type { UiRoomEvent } from '@/contracts/ui-events';
import { parseContract } from '@/contracts/validators';

export type RoomQuestionOption = QuestionOption;

export interface PendingRoomQuestion {
  postId: string;
  roomId: string;
  rootId: string;
  sequence: number;
  prompt: string;
  options: RoomQuestionOption[];
}

export function latestUnresolvedRoomQuestion(
  events: readonly UiRoomEvent[],
  initial?: PendingRoomQuestion,
): PendingRoomQuestion | undefined {
  let pending = initial;
  const ordered = [...events].sort((left, right) => left.sequence - right.sequence);
  for (const event of ordered) {
    if (event.eventType === 'user_message') {
      if (pending && event.sequence > pending.sequence) pending = undefined;
      continue;
    }
    if (event.eventType !== 'room_post') continue;
    const question = structuredWaitQuestion(event);
    if (question && (!pending || question.sequence > pending.sequence)) pending = question;
  }
  return pending;
}

function structuredWaitQuestion(event: UiRoomEvent): PendingRoomQuestion | undefined {
  let post: RoomPostV2;
  try {
    post = parseContract('room-post.v2', event.payload.post);
  } catch {
    return undefined;
  }
  if (
    post.kind !== 'wait'
    || !post.question
    || post.roomId !== event.roomId
    || post.rootId !== event.turnId
  ) return undefined;
  const options = [...post.question.options];
  if (
    new Set(options.map((option) => option.value)).size !== options.length
    || options.filter((option) => option.recommended).length > 1
  ) return undefined;
  return {
    postId: post.postId,
    roomId: post.roomId,
    rootId: post.rootId,
    sequence: event.sequence,
    prompt: post.question.prompt,
    options,
  };
}
