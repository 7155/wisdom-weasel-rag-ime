import { describe, expect, it } from 'vitest';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import { buildCancelRootCommand, createFixtureRoomKernelCommandTransport } from './room-kernel-command-transport';

describe('Room kernel fixture command transport', () => {
  it('builds a generated typed cancel command bound to Room Root generation', () => {
    const command = buildCancelRootCommand(
      { roomId: 'room-a', rootId: 'root-a', generation: 7 },
      { commandId: 'command-7', sourceId: 'test', createdAtMs: 10 },
    );
    expect(command).toMatchObject({
      commandKind: 'cancel_root', targetKind: 'root', targetId: 'root-a',
      roomId: 'room-a', rootId: 'root-a', generation: 7,
    });
    expect(command.idempotencyKey).toContain('room-a:root-a:7:command-7');
  });

  it.each([
    ['another command', { commandId: 'wrong' }],
    ['another Root', { rootId: 'root-b' }],
    ['a stale generation', { generation: 6 }],
  ])('rejects a receipt for %s', async (_label, override) => {
    const command = buildCancelRootCommand(
      { roomId: 'room-a', rootId: 'root-a', generation: 7 },
      { commandId: 'command-7', sourceId: 'test', createdAtMs: 10 },
    );
    const transport = createFixtureRoomKernelCommandTransport(() => receipt({
      commandId: command.commandId, rootId: command.rootId, generation: command.generation, ...override,
    }));
    await expect(transport.execute(command)).rejects.toThrow(/does not match/);
  });
});

function receipt(overrides: Partial<RoomKernelReceiptV1>): RoomKernelReceiptV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1', receiptId: 'receipt-a', rootId: 'root-a',
    commandId: 'command-7', receiptKind: 'root_cancelled', status: 'applied', generation: 7,
    details: {}, createdAtMs: 11, ...overrides,
  };
}
