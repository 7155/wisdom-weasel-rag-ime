import { useControlTransport } from '@/app/control-transport';
import { useRoomLiveSession } from '@/features/rooms/runtime/use-room-live-session';
import { pulsePawCompositionForRuntimeEvents } from '../runtime/composition-pulse';

/**
 * A satellite Room surface still needs its canonical live projection when its
 * main Room window is minimized. This component is lazy so an ordinary desktop
 * never pays for the Room reducer and generated contract validators.
 */
export default function PawRoomProjectionKeeper({ roomId }: { roomId: string }) {
  const transport = useControlTransport();
  useRoomLiveSession({
    roomId,
    transport,
    onLoadingChange: () => undefined,
    onSnapshot: () => undefined,
    onMetadata: () => undefined,
    onConnectionRestored: () => undefined,
    onConnectionError: () => undefined,
    onRecoveryState: () => undefined,
    onEvents: (_roomId, events) => pulsePawCompositionForRuntimeEvents('room', events.map((event) => event.eventType)),
  });
  return null;
}
