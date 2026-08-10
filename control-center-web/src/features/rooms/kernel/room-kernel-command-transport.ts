import type { RoomKernelCommandV1 } from '@/contracts/generated/room-kernel-command.v1';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import { parseContract } from '@/contracts/validators';
import type { ControlTransport, JsonValue } from '@/platform/transport';

export type RootStopTarget = {
  roomId: string;
  rootId: string;
  generation: number;
};

export type RoomKernelCancelTarget = RootStopTarget & {
  targetKind: 'task' | 'dispatch';
  targetId: string;
};

export interface RoomKernelCommandTransport {
  readonly kind: 'fixture' | 'control';
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
    sourceKind: 'control_center',
    sourceId: identity.sourceId,
    idempotencyKey: `cancel-root:${target.roomId}:${target.rootId}:${target.generation}:${identity.commandId}`,
    generation: target.generation,
    payload: {},
    createdAtMs: identity.createdAtMs,
  };
  return parseContract('room-kernel-command.v1', command);
}

export function buildCancelTargetCommand(
  target: RoomKernelCancelTarget,
  identity: { commandId: string; sourceId: string; createdAtMs: number },
): RoomKernelCommandV1 {
  return parseContract('room-kernel-command.v1', {
    schemaVersion: 'wisdom-weasel.room-kernel-command.v1',
    commandId: identity.commandId,
    rootId: target.rootId,
    roomId: target.roomId,
    commandKind: 'cancel_target',
    targetKind: target.targetKind,
    targetId: target.targetId,
    sourceKind: 'control_center',
    sourceId: identity.sourceId,
    idempotencyKey: [
      'cancel-target',
      target.roomId,
      target.rootId,
      target.targetKind,
      target.targetId,
      target.generation,
      identity.commandId,
    ].join(':'),
    generation: target.generation,
    payload: {},
    createdAtMs: identity.createdAtMs,
  });
}

export function buildRetryRootCommand(
  target: RootStopTarget,
  identity: { commandId: string; sourceId: string; createdAtMs: number },
): RoomKernelCommandV1 {
  return parseContract('room-kernel-command.v1', {
    schemaVersion: 'wisdom-weasel.room-kernel-command.v1',
    commandId: identity.commandId,
    rootId: target.rootId,
    roomId: target.roomId,
    commandKind: 'retry_root',
    targetKind: 'root',
    targetId: target.rootId,
    sourceKind: 'control_center',
    sourceId: identity.sourceId,
    idempotencyKey: `retry-root:${target.roomId}:${target.rootId}:${target.generation}:${identity.commandId}`,
    generation: target.generation,
    payload: {},
    createdAtMs: identity.createdAtMs,
  });
}

export function buildPanicCommand(
  roomId: string,
  identity: { commandId: string; sourceId: string; createdAtMs: number },
): RoomKernelCommandV1 {
  return parseContract('room-kernel-command.v1', {
    schemaVersion: 'wisdom-weasel.room-kernel-command.v1',
    commandId: identity.commandId,
    rootId: null,
    roomId,
    commandKind: 'panic',
    targetKind: null,
    targetId: null,
    sourceKind: 'control_center_admin',
    sourceId: identity.sourceId,
    idempotencyKey: `panic:${roomId}:${identity.commandId}`,
    generation: 0,
    payload: {},
    createdAtMs: identity.createdAtMs,
  });
}

/** Explicit test/demo adapter over the same command contract used by ControlTransport. */
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

function validateReceiptGeneration(
  command: RoomKernelCommandV1,
  receipt: RoomKernelReceiptV1,
): void {
  const expected = command.commandKind === 'cancel_root' ? command.generation + 1 : command.generation;
  if (receipt.generation !== expected) throw new TypeError('Kernel receipt generation does not match command transition');
}
