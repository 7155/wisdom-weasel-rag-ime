import { useEffect, useMemo, useState } from 'react';
import type { RoomEventEnvelopeV2 } from '@/contracts/generated/room-event-envelope.v2';
import {
  applyRoomKernelSnapshot,
  createRoomKernelProjection,
  reduceRoomKernelEvent,
  type RoomKernelProjection,
  type RoomKernelSnapshot,
} from '@/contracts/room-kernel-reducer';
import { parseContract } from '@/contracts/validators';
import { useControlTransport } from '@/app/control-transport';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';
import { createControlRoomKernelCommandTransport } from './room-kernel-command-transport';

export function RoomKernelLivePanel({ roomId }: { roomId: string }) {
  const transport = useControlTransport();
  const [projection, setProjection] = useState<RoomKernelProjection | null>(null);
  const commandTransport = useMemo(
    () => createControlRoomKernelCommandTransport(transport),
    [transport],
  );

  useEffect(() => {
    let active = true;
    let unsubscribe: (() => void) | undefined;
    let revision = 0;

    const load = async () => {
      const currentRevision = ++revision;
      unsubscribe?.();
      unsubscribe = undefined;
      try {
        const raw = await transport.request({
          pathId: 'agent.room.kernel.snapshot',
          params: { roomId },
        });
        if (!active || currentRevision !== revision) return;
        const snapshot = raw as RoomKernelSnapshot;
        const next = applyRoomKernelSnapshot(createRoomKernelProjection(roomId), snapshot);
        setProjection(next);
        unsubscribe = transport.subscribe<unknown>(
          {
            pathId: 'agent.room.kernel.events',
            params: { roomId },
            lastEventId: `${roomId}#${next.lastSequence}`,
          },
          {
            next: (value) => {
              if (!active || isSnapshotRequired(value)) return;
              const event = parseContract('room-event-envelope.v2', value) as RoomEventEnvelopeV2;
              setProjection((current) => {
                if (!current) return current;
                const reduced = reduceRoomKernelEvent(current, event);
                if (reduced.disposition === 'snapshot-required') void load();
                return reduced.state;
              });
            },
            snapshotRequired: () => { if (active) void load(); },
          },
        );
      } catch {
        if (active && currentRevision === revision) setProjection(null);
      }
    };

    void load();
    return () => {
      active = false;
      revision += 1;
      unsubscribe?.();
    };
  }, [roomId, transport]);

  if (!projection || Object.keys(projection.rootsById).length === 0) return null;
  return <RoomKernelControlPlane
    projection={projection}
    budgetsByRootId={{}}
    contextReceiptsByRootId={{}}
    capabilityReceiptsByRootId={{}}
    commandTransport={commandTransport}
  />;
}

function isSnapshotRequired(value: unknown): boolean {
  return Boolean(value && typeof value === 'object' && 'reason' in value && value.reason === 'event_replay_gap');
}
