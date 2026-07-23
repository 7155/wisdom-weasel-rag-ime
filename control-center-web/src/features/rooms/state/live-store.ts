import { create, type StoreApi } from 'zustand';

import {
  abortRoomParticipantTurn,
  abortRoomTurn,
  appendOptimisticRoomMessage,
  createRoomProjection,
  reduceRoomEvent,
  replayRoomEventSnapshot,
  type RoomEventSnapshot,
  type RoomProjectionState,
} from '@/contracts/room-reducer';
import type { UiRoomEvent } from '@/contracts/ui-events';
import { mergeAcceptedRoomTimeline } from '../runtime/accepted-room-timeline';

interface RoomLiveStore {
  projections: Record<string, RoomProjectionState>;
  roomRevisions: Record<string, number>;
  turnRevisions: Record<string, Record<string, number>>;
  ensure(roomId: string): void;
  replaySnapshot(roomId: string, snapshot: RoomEventSnapshot): void;
  applyEvents(roomId: string, events: readonly UiRoomEvent[]): boolean;
  appendOptimistic(
    roomId: string,
    input: { clientMessageId: string; text: string; nowMs: number },
  ): void;
  acceptMessage(roomId: string, response: Record<string, unknown>): void;
  discardOptimistic(roomId: string, clientMessageId: string): void;
  abortTurn(roomId: string, turnId: string, nowMs: number): void;
  abortParticipant(
    roomId: string,
    turnId: string,
    participantId: string,
    nowMs: number,
  ): void;
  remove(roomId: string): void;
  reset(): void;
}

export const useRoomLiveStore = create<RoomLiveStore>((set, get) => ({
  projections: {},
  roomRevisions: {},
  turnRevisions: {},
  ensure(roomId) {
    if (!roomId || get().projections[roomId]) return;
    set((state) => ({
      projections: {
        ...state.projections,
        [roomId]: createRoomProjection(roomId),
      },
    }));
  },
  replaySnapshot(roomId, snapshot) {
    const current = roomProjection(roomId);
    const next = replayRoomEventSnapshot(current, snapshot);
    replaceProjection(set, get, roomId, next, allTurnIds(current, next));
  },
  applyEvents(roomId, events) {
    const current = roomProjection(roomId);
    let projection = current;
    let snapshotRequired = false;
    const changedTurnIds = new Set<string>();
    for (const event of events) {
      const reduced = reduceRoomEvent(projection, event);
      projection = reduced.state;
      snapshotRequired ||= reduced.disposition === 'snapshot-required';
      if (reduced.disposition === 'applied' && event.turnId) {
        changedTurnIds.add(event.turnId);
      }
    }
    if (projection !== current) {
      replaceProjection(set, get, roomId, projection, changedTurnIds);
    }
    return snapshotRequired;
  },
  appendOptimistic(roomId, input) {
    const current = roomProjection(roomId);
    const next = appendOptimisticRoomMessage(current, input);
    const messageId = next.optimisticByClientMessageId[input.clientMessageId];
    const turnId = messageId ? next.messagesById[messageId]?.turnId : '';
    replaceProjection(set, get, roomId, next, turnId ? [turnId] : []);
  },
  acceptMessage(roomId, response) {
    const current = roomProjection(roomId);
    const next = mergeAcceptedRoomTimeline(current, response);
    replaceProjection(set, get, roomId, next, allTurnIds(current, next));
  },
  discardOptimistic(roomId, clientMessageId) {
    const current = roomProjection(roomId);
    const messageId = current.optimisticByClientMessageId[clientMessageId];
    const turnId = messageId ? current.messagesById[messageId]?.turnId : '';
    const next = discardOptimisticRoomMessage(current, clientMessageId);
    replaceProjection(set, get, roomId, next, turnId ? [turnId] : []);
  },
  abortTurn(roomId, turnId, nowMs) {
    const current = roomProjection(roomId);
    const next = abortRoomTurn(current, turnId, nowMs);
    replaceProjection(set, get, roomId, next, [turnId]);
  },
  abortParticipant(roomId, turnId, participantId, nowMs) {
    const current = roomProjection(roomId);
    const next = abortRoomParticipantTurn(
      current,
      turnId,
      participantId,
      nowMs,
    );
    replaceProjection(set, get, roomId, next, [turnId]);
  },
  remove(roomId) {
    set((state) => {
      const projections = { ...state.projections };
      const roomRevisions = { ...state.roomRevisions };
      const turnRevisions = { ...state.turnRevisions };
      delete projections[roomId];
      delete roomRevisions[roomId];
      delete turnRevisions[roomId];
      return { projections, roomRevisions, turnRevisions };
    });
  },
  reset() {
    set({ projections: {}, roomRevisions: {}, turnRevisions: {} });
  },
}));

export function roomProjection(roomId: string): RoomProjectionState {
  return (
    useRoomLiveStore.getState().projections[roomId]
    ?? createRoomProjection(roomId)
  );
}

export function discardOptimisticRoomMessage(
  state: RoomProjectionState,
  clientMessageId: string,
): RoomProjectionState {
  const messageId = state.optimisticByClientMessageId[clientMessageId];
  if (!messageId) return state;
  const message = state.messagesById[messageId];
  const next: RoomProjectionState = {
    ...state,
    messagesById: { ...state.messagesById },
    messageOrder: state.messageOrder.filter((id) => id !== messageId),
    turnsById: { ...state.turnsById },
    turnOrder: [...state.turnOrder],
    optimisticByClientMessageId: { ...state.optimisticByClientMessageId },
  };
  delete next.messagesById[messageId];
  delete next.optimisticByClientMessageId[clientMessageId];
  if (!message) return next;
  const turn = next.turnsById[message.turnId];
  if (!turn) return next;
  const messageIds = turn.messageIds.filter((id) => id !== messageId);
  if (messageIds.length || turn.activityIds.length) {
    next.turnsById[turn.id] = { ...turn, messageIds };
  } else {
    delete next.turnsById[turn.id];
    next.turnOrder = next.turnOrder.filter((id) => id !== turn.id);
  }
  return next;
}

function replaceProjection(
  set: StoreApi<RoomLiveStore>['setState'],
  get: StoreApi<RoomLiveStore>['getState'],
  roomId: string,
  projection: RoomProjectionState,
  changedTurnIds: Iterable<string>,
): void {
  const current = get().projections[roomId];
  if (current === projection) return;
  set((state) => {
    const roomTurnRevisions = { ...(state.turnRevisions[roomId] ?? {}) };
    for (const turnId of changedTurnIds) {
      if (!turnId) continue;
      roomTurnRevisions[turnId] = (roomTurnRevisions[turnId] ?? 0) + 1;
    }
    return {
      projections: { ...state.projections, [roomId]: projection },
      roomRevisions: {
        ...state.roomRevisions,
        [roomId]: (state.roomRevisions[roomId] ?? 0) + 1,
      },
      turnRevisions: {
        ...state.turnRevisions,
        [roomId]: roomTurnRevisions,
      },
    };
  });
}

function allTurnIds(
  current: RoomProjectionState,
  next: RoomProjectionState,
): Set<string> {
  return new Set([...current.turnOrder, ...next.turnOrder]);
}
