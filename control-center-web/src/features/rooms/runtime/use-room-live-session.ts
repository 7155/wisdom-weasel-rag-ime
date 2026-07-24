import { useEffect, useRef } from 'react';

import { createRoomDeltaBatcher } from '@/contracts/batching';
import {
  parseRoomEventSnapshot,
  type RoomEventSnapshot,
} from '@/contracts/room-reducer';
import type { UiRoomEvent } from '@/contracts/ui-events';
import type { ControlTransport } from '@/platform/transport';
import { useRoomLiveStore } from '../state/live-store';

interface RoomLiveSessionCallbacks {
  onLoadingChange(loading: boolean): void;
  onSnapshot(roomId: string, snapshot: RoomEventSnapshot): void;
  onMetadata(roomId: string, response: unknown): void;
  onConnectionRestored(roomId: string): void;
  onConnectionError(roomId: string, error: unknown, fallback: string): void;
}

export function useRoomLiveSession({
  roomId,
  transport,
  ...callbacks
}: {
  roomId: string;
  transport: ControlTransport;
} & RoomLiveSessionCallbacks): void {
  const callbacksRef = useRef<RoomLiveSessionCallbacks>(callbacks);
  callbacksRef.current = callbacks;

  useEffect(() => {
    if (!roomId) {
      callbacksRef.current.onLoadingChange(false);
      return;
    }

    let active = true;
    let generation = 0;
    let reloadQueued = false;
    let metadataRefreshQueued = false;
    let metadataRefreshRunning = false;
    let metadataRefreshPending = false;
    let unsubscribe: (() => void) | undefined;
    let snapshotController: AbortController | undefined;
    let metadataController: AbortController | undefined;
    useRoomLiveStore.getState().ensure(roomId);
    callbacksRef.current.onLoadingChange(true);

    const scheduleSnapshotReload = () => {
      if (!active || reloadQueued) return;
      reloadQueued = true;
      queueMicrotask(() => {
        reloadQueued = false;
        if (active) void loadSnapshotAndSubscribe();
      });
    };
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
        if (active && !isAbortError(error)) {
          callbacksRef.current.onConnectionError(
            roomId,
            error,
            'Room 状态暂时无法刷新，实时对话仍在继续。',
          );
        }
      } finally {
        metadataRefreshRunning = false;
        metadataController = undefined;
        if (active && metadataRefreshPending) scheduleMetadataRefresh();
      }
    }

    async function loadSnapshotAndSubscribe(): Promise<void> {
      const requestGeneration = ++generation;
      batcher.clear();
      unsubscribe?.();
      unsubscribe = undefined;
      snapshotController?.abort();
      snapshotController = new AbortController();
      try {
        const value = await transport.request({
          pathId: 'agent.room.snapshot',
          params: { roomId },
          signal: snapshotController.signal,
        });
        if (!active || requestGeneration !== generation) return;
        const snapshot = parseRoomEventSnapshot(value);
        useRoomLiveStore.getState().replaySnapshot(roomId, snapshot);
        callbacksRef.current.onLoadingChange(false);
        callbacksRef.current.onSnapshot(roomId, snapshot);
        callbacksRef.current.onConnectionRestored(roomId);
        const subscriptionGeneration = requestGeneration;
        unsubscribe = transport.subscribe<UiRoomEvent>(
          {
            pathId: 'agent.room.events',
            params: { roomId },
            lastEventId: snapshot.resumeToken,
          },
          {
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
                callbacksRef.current.onConnectionError(
                  roomId,
                  error,
                  'Room 实时连接暂时中断，请稍后重试。',
                );
              }
            },
            snapshotRequired: () => {
              if (active && subscriptionGeneration === generation) {
                scheduleSnapshotReload();
              }
            },
          },
        );
      } catch (error) {
        if (
          active
          && requestGeneration === generation
          && !isAbortError(error)
        ) {
          callbacksRef.current.onConnectionError(
            roomId,
            error,
            '暂时无法读取 Room 对话，请稍后重试。',
          );
          callbacksRef.current.onLoadingChange(false);
        }
      }
    }

    void loadSnapshotAndSubscribe();
    return () => {
      active = false;
      generation += 1;
      snapshotController?.abort();
      metadataController?.abort();
      batcher.clear();
      unsubscribe?.();
    };
  }, [roomId, transport]);
}

function isAbortError(value: unknown): boolean {
  return value instanceof DOMException && value.name === 'AbortError';
}
