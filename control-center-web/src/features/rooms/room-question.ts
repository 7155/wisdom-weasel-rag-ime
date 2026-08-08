import type {
  PendingRoomQuestionProjection,
} from '@/contracts/room-reducer';
import type { RootProjection } from '@/contracts/room-kernel-reducer';

export type PendingRoomQuestion = PendingRoomQuestionProjection;
export type RoomQuestionAnswerKind = 'option' | 'custom';

const ANSWERABLE_ROOT_STATES: ReadonlySet<RootProjection['state']> = new Set([
  'pending',
  'running',
  'waiting',
]);

/** Only the current Kernel Root may authorize an interactive answer control. */
export function answerableRoomQuestion(
  question: PendingRoomQuestion | undefined,
  rootsById: Readonly<Record<string, RootProjection>>,
): PendingRoomQuestion | undefined {
  if (!question) return undefined;
  const root = rootsById[question.rootId];
  return root && ANSWERABLE_ROOT_STATES.has(root.state)
    ? question
    : undefined;
}
