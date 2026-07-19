import type { RoomKernelCommandV1 } from '@/contracts/generated/room-kernel-command.v1';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import { parseContract } from '@/contracts/validators';

export type RootStopTarget = {
  roomId: string;
  rootId: string;
  generation: number;
};

export interface RoomKernelCommandTransport {
  readonly kind: 'fixture';
  execute(command: RoomKernelCommandV1): Promise<RoomKernelReceiptV1>;
}

export function buildCancelRootCommand(
  target: RootStopTarget,
  identity: { commandId: string; sourceId: string; createdAtMs: number },
): RoomKernelCommandV1 {
  const command: RoomKernelCommandV1 = {
    schemaVersion: 'wisdom-weasel.room-kernel-command.v1',
    commandId: identity.commandId,
    rootId: target.rootId,
    roomId: target.roomId,
    commandKind: 'cancel_root',
    targetKind: 'root',
    targetId: target.rootId,
    sourceKind: 'control_center_fixture',
    sourceId: identity.sourceId,
    idempotencyKey: `cancel-root:${target.roomId}:${target.rootId}:${target.generation}:${identity.commandId}`,
    generation: target.generation,
    payload: {},
    createdAtMs: identity.createdAtMs,
  };
  return parseContract('room-kernel-command.v1', command);
}

/** Explicit test/demo transport. Production remains read-only until a backend command route exists. */
export function createFixtureRoomKernelCommandTransport(
  handler: (command: RoomKernelCommandV1) => RoomKernelReceiptV1 | Promise<RoomKernelReceiptV1>,
): RoomKernelCommandTransport {
  return {
    kind: 'fixture',
    async execute(input) {
      const command = parseContract('room-kernel-command.v1', input);
      const receipt = parseContract('room-kernel-receipt.v1', await handler(command));
      if (receipt.commandId !== command.commandId) throw new TypeError('Kernel receipt does not match command');
      if (receipt.rootId !== command.rootId) throw new TypeError('Kernel receipt does not match Root');
      if (receipt.generation !== command.generation) throw new TypeError('Kernel receipt generation does not match command');
      return receipt;
    },
  };
}
