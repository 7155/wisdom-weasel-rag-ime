import { useCallback, useEffect, useRef } from 'react';

import { createRoomDeltaBatcher } from '@/contracts/batching';
import {
  parseRoomEventSnapshot,
  type RoomEventSnapshot,
} from '@/contracts/room-reducer';
import type { UiRoomEvent } from '@/contracts/ui-events';
import type { ControlTransport } from '@/platform/transport';
import { useRoomLiveStore } from '../state/live-store';

const ROOM_RECOVERY_BASE_DELAY_MS = 1_000;
const ROOM_RECOVERY_MAX_DELAY_MS = 15_000;
const ROOM_RECOVERY_VISIBLE_RETRY_ATTEMPT = 3;

interface RoomLiveSessionCallbacks {
  onLoadingChange(loading: boolean): void;
  onSnapshot(roomId: string, snapshot: RoomEventSnapshot): void;
  onMetadata(roomId: string, response: unknown): void;
  onConnectionRestored(roomId: string): void;
  onConnectionError(roomId: string, error: unknown, fallback: string): void;
  onRecoveryState(roomId: string, state: 'recovering' | 'failed' | 'synced'): void;
  onEvents(roomId: string, events: readonly UiRoomEvent[]): void;
}

export function useRoomLiveSession({
  roomId,
  transport,
  ...callbacks
}: {
  roomId: string;
  transport: ControlTransport;
} & RoomLiveSessionCallbacks): () => void {
  const callbacksRef = useRef<RoomLiveSessionCallbacks>(callbacks);
  const retrySnapshotRef = useRef<() => void>(() => undefined);
  const retrySnapshot = useCallback(() => retrySnapshotRef.current(), []);
  callbacksRef.current = callbacks;

  useEffect(() => {
    if (!roomId) {
      retrySnapshotRef.current = () => undefined;
      callbacksRef.current.onLoadingChange(false);
      return;
    }

    let active = true;
    let generation = 0;
    let reloadQueued = false;
    let snapshotRunning = false;
    let snapshotReloadPending = false;
    let recoveryAttempt = 0;
    let recoveryTimer: ReturnType<typeof setTimeout> | undefined;
    let metadataRefreshQueued = false;
    let metadataRefreshRunning = false;
    let metadataRefreshPending = false;
    let unsubscribe: (() => void) | undefined;
    let snapshotController: AbortController | undefined;
    let metadataController: AbortController | undefined;
    useRoomLiveStore.getState().ensure(roomId);
    callbacksRef.current.onLoadingChange(true);

    const clearRecoveryTimer = () => {
      if (recoveryTimer === undefined) return;
      clearTimeout(recoveryTimer);
      recoveryTimer = undefined;
    };
    const resetRecoveryBackoff = () => {
      recoveryAttempt = 0;
      clearRecoveryTimer();
    };
    const scheduleSnapshotReload = (resetBackoff = false) => {
      if (resetBackoff) resetRecoveryBackoff();
      else clearRecoveryTimer();
      if (snapshotRunning) {
        snapshotReloadPending = true;
        return;
      }
      if (!active || reloadQueued) return;
      reloadQueued = true;
      queueMicrotask(() => {
        reloadQueued = false;
        if (active) void loadSnapshotAndSubscribe();
      });
    };
    const retrySnapshot = () => {
      if (!active) return;
      callbacksRef.current.onRecoveryState(roomId, 'recovering');
      scheduleSnapshotReload(true);
    };
    const scheduleAutomaticRecovery = () => {
      if (!active || recoveryTimer !== undefined || reloadQueued || snapshotReloadPending) return;
      const attempt = recoveryAttempt + 1;
      const delayMs = Math.min(
        ROOM_RECOVERY_BASE_DELAY_MS * (2 ** recoveryAttempt),
        ROOM_RECOVERY_MAX_DELAY_MS,
      );
      recoveryAttempt = attempt;
      callbacksRef.current.onRecoveryState(
        roomId,
        attempt >= ROOM_RECOVERY_VISIBLE_RETRY_ATTEMPT ? 'failed' : 'recovering',
      );
      recoveryTimer = setTimeout(() => {
        recoveryTimer = undefined;
        if (active) scheduleSnapshotReload();
      }, delayMs);
    };
    retrySnapshotRef.current = retrySnapshot;
    const scheduleMetadataRefresh = () => {
      if (!active) return;
      metadataRefreshPending = true;
      if (metadataRefreshQueued || metadataRefreshRunning) return;
      metadataRefreshQueued = true;
      queueMicrotask(() => {
        metadataRefreshQueued = false;
        if (active) void refreshRoomMetadata();
      });
    };
    const batcher = createRoomDeltaBatcher((events) => {
      if (!active) return;
      const snapshotRequired = useRoomLiveStore
        .getState()
        .applyEvents(roomId, events);
      if (snapshotRequired) scheduleSnapshotReload();
      else callbacksRef.current.onEvents(roomId, events);
    });

    async function refreshRoomMetadata(): Promise<void> {
      if (!active || metadataRefreshRunning || !metadataRefreshPending) return;
      metadataRefreshPending = false;
      metadataRefreshRunning = true;
      metadataController = new AbortController();
      try {
        const response = await transport.request({
          pathId: 'agent.room.get',
          params: { roomId },
          signal: metadataController.signal,
        });
        if (active) callbacksRef.current.onMetadata(roomId, response);
      } catch (error) {
        // Metadata is best-effort. The snapshot and event stream remain the
        // authoritative Room projection, so a late detail refresh must not
        // turn a healthy live conversation into a global timeout state.
        void error;
      } finally {
        metadataRefreshRunning = false;
        metadataController = undefined;
        if (active && metadataRefreshPending) scheduleMetadataRefresh();
      }
    }

    async function loadSnapshotAndSubscribe(): Promise<void> {
      if (snapshotRunning) {
        snapshotReloadPending = true;
        return;
      }
      snapshotRunning = true;
      callbacksRef.current.onRecoveryState(roomId, 'recovering');
      callbacksRef.current.onLoadingChange(true);
      const requestGeneration = ++generation;
      batcher.clear();
      unsubscribe?.();
      unsubscribe = undefined;
      snapshotController = new AbortController();
      try {
        const value = await transport.request({
          pathId: 'agent.room.snapshot',
          params: { roomId },
          signal: snapshotController.signal,
        });
        if (!active || requestGeneration !== generation) return;
        const snapshot = parseRoomEventSnapshot(value);
        const snapshotApplied = useRoomLiveStore.getState().replaySnapshot(roomId, snapshot);
        const resumeToken = useRoomLiveStore.getState().projections[roomId]?.resumeToken
          ?? snapshot.resumeToken;
        callbacksRef.current.onLoadingChange(false);
        if (snapshotApplied) callbacksRef.current.onSnapshot(roomId, snapshot);
        const subscriptionGeneration = requestGeneration;
        unsubscribe = transport.subscribe<UiRoomEvent>(
          {
            pathId: 'agent.room.events',
            params: { roomId },
            lastEventId: resumeToken,
          },
          {
            open: () => {
              if (!active || subscriptionGeneration !== generation) return;
              resetRecoveryBackoff();
              callbacksRef.current.onRecoveryState(roomId, 'synced');
              callbacksRef.current.onConnectionRestored(roomId);
            },
            next: (event) => {
              if (!active || subscriptionGeneration !== generation) return;
              batcher.push(event);
              if (
                ['room_config_changed', 'topic_changed', 'artifact_changed'].includes(
                  event.eventType,
                )
                || (
                  event.eventType === 'participant_activity'
                  && event.payload.activityKind === 'work'
                )
              ) {
                scheduleMetadataRefresh();
              }
            },
            error: (error) => {
              if (active && subscriptionGeneration === generation) {
                unsubscribe?.();
                unsubscribe = undefined;
                generation += 1;
                callbacksRef.current.onRecoveryState(roomId, 'failed');
                callbacksRef.current.onConnectionError(
                  roomId,
                  error,
                  'Room 实时连接暂时中断，请稍后重试。',
                );
                scheduleAutomaticRecovery();
              }
            },
            snapshotRequired: () => {
              if (active && subscriptionGeneration === generation) {
                scheduleSnapshotReload();
              }
            },
          },
        );
        // Connection state is cleared by the stream's open callback, not merely
        // because subscription setup returned.
      } catch (error) {
        if (
          active
          && requestGeneration === generation
          && !isAbortError(error)
        ) {
          callbacksRef.current.onRecoveryState(roomId, 'failed');
          callbacksRef.current.onConnectionError(
            roomId,
            error,
            '暂时无法同步 Room 对话；已显示的历史消息会保留，实时更新已暂停。',
          );
          callbacksRef.current.onLoadingChange(false);
          scheduleAutomaticRecovery();
        }
      } finally {
        snapshotRunning = false;
        snapshotController = undefined;
        if (active && snapshotReloadPending) {
          snapshotReloadPending = false;
          scheduleSnapshotReload();
        }
      }
    }

    void loadSnapshotAndSubscribe();
    return () => {
      if (retrySnapshotRef.current === retrySnapshot) {
        retrySnapshotRef.current = () => undefined;
      }
      active = false;
      generation += 1;
      clearRecoveryTimer();
      snapshotController?.abort();
      metadataController?.abort();
      batcher.clear();
      unsubscribe?.();
    };
  }, [roomId, transport]);
  return retrySnapshot;
}

function isAbortError(value: unknown): boolean {
  return value instanceof DOMException && value.name === 'AbortError';
}
