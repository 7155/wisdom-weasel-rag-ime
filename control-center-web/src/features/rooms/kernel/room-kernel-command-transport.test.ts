import { describe, expect, it } from 'vitest';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { buildCancelRootCommand, buildPanicCommand, createControlRoomKernelCommandTransport, createFixtureRoomKernelCommandTransport } from './room-kernel-command-transport';

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

  it('builds a Room-wide panic command without pretending it targets one Root', () => {
    expect(buildPanicCommand('room-a', { commandId: 'panic-a', sourceId: 'admin', createdAtMs: 12 }))
      .toMatchObject({ commandKind: 'panic', roomId: 'room-a', rootId: null, targetKind: null, targetId: null, generation: 0 });
  });

  it.each([
    ['another command', { commandId: 'wrong', generation: 8 }],
    ['another Root', { rootId: 'root-b', generation: 8 }],
    ['a stale generation', { generation: 7 }],
  ])('rejects a receipt for %s', async (_label, override) => {
    const command = buildCancelRootCommand(
      { roomId: 'room-a', rootId: 'root-a', generation: 7 },
      { commandId: 'command-7', sourceId: 'test', createdAtMs: 10 },
    );
    const transport = createFixtureRoomKernelCommandTransport(() => receipt({
      commandId: command.commandId, rootId: command.rootId, ...override,
    }));
    await expect(transport.execute(command)).rejects.toThrow(/does not match/);
  });

  it('uses the single ControlTransport production route and validates its receipt contract', async () => {
    const control = new MockControlTransport({
      routes: {
        'agent.room.kernel.command': (request: ControlRequest) => receipt({
          commandId: (request.body as Record<string, unknown>).commandId as string,
          rootId: 'root-a', generation: 8,
        }),
      },
    });
    const command = buildCancelRootCommand(
      { roomId: 'room-a', rootId: 'root-a', generation: 7 },
      { commandId: 'command-7', sourceId: 'test', createdAtMs: 10 },
    );
    await expect(createControlRoomKernelCommandTransport(control).execute(command))
      .resolves.toMatchObject({ receiptKind: 'root_cancelled', generation: 8 });
    expect(control.requests[0]?.request).toMatchObject({
      pathId: 'agent.room.kernel.command', params: { roomId: 'room-a' },
      responseContract: 'room-kernel-receipt.v1',
    });
  });

});

function receipt(overrides: Partial<RoomKernelReceiptV1>): RoomKernelReceiptV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1', receiptId: 'receipt-a', rootId: 'root-a',
    commandId: 'command-7', receiptKind: 'root_cancelled', status: 'applied', generation: 7,
    details: {}, createdAtMs: 11, ...overrides,
  };
}
