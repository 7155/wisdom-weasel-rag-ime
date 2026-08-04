import type {
  PendingRoomQuestionProjection,
} from '@/contracts/room-reducer';

export type PendingRoomQuestion = PendingRoomQuestionProjection;
export type RoomQuestionAnswerKind = 'option' | 'custom';
