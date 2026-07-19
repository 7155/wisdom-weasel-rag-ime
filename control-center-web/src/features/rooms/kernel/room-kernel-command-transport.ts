import type { RoomKernelCommandV1 } from '@/contracts/generated/room-kernel-command.v1';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import { parseContract } from '@/contracts/validators';
import type { ControlTransport, JsonValue } from '@/platform/transport';

export type RootStopTarget = {
  roomId: string;
  rootId: string;
  generation: number;
};

export interface RoomKernelCommandTransport {
  readonly kind: 'fixture' | 'http' | 'control';
  execute(command: RoomKernelCommandV1): Promise<RoomKernelReceiptV1>;
}

export function createControlRoomKernelCommandTransport(
  transport: ControlTransport,
): RoomKernelCommandTransport {
  return {
    kind: 'control',
    async execute(input) {
      const command = parseContract('room-kernel-command.v1', input);
      const payload = await transport.request({
        pathId: 'agent.room.kernel.command',
        params: { roomId: command.roomId },
        body: command as unknown as JsonValue,
        responseContract: 'room-kernel-receipt.v1',
      });
      const receipt = parseContract('room-kernel-receipt.v1', payload);
      if (receipt.commandId !== command.commandId) throw new TypeError('Kernel receipt does not match command');
      if (receipt.rootId !== command.rootId) throw new TypeError('Kernel receipt does not match Root');
      validateReceiptGeneration(command, receipt);
      return receipt;
    },
  };
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

/** Explicit test/demo transport. Production uses the authenticated HTTP command route below. */
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
      validateReceiptGeneration(command, receipt);
      return receipt;
    },
  };
}

export function createHttpRoomKernelCommandTransport(
  fetcher: typeof fetch = fetch,
): RoomKernelCommandTransport {
  return {
    kind: 'http',
    async execute(input) {
      const command = parseContract('room-kernel-command.v1', input);
      const response = await fetcher(
        `/api/agent/rooms/${encodeURIComponent(command.roomId)}/kernel/commands`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(command),
        },
      );
      if (!response.ok) throw new Error(`Room Kernel command failed (${response.status})`);
      const receipt = parseContract('room-kernel-receipt.v1', await response.json());
      if (receipt.commandId !== command.commandId) throw new TypeError('Kernel receipt does not match command');
      if (receipt.rootId !== command.rootId) throw new TypeError('Kernel receipt does not match Root');
      validateReceiptGeneration(command, receipt);
      return receipt;
    },
  };
}

function validateReceiptGeneration(
  command: RoomKernelCommandV1,
  receipt: RoomKernelReceiptV1,
): void {
  const expected = command.commandKind === 'cancel_root' ? command.generation + 1 : command.generation;
  if (receipt.generation !== expected) throw new TypeError('Kernel receipt generation does not match command transition');
}
