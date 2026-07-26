import { describe, expect, it } from 'vitest';
import { parseRoomRequirementsReadProjection } from '@/features/rooms/requirements/room-requirements-read-model';
import {
  buildCancelRootCommand,
  createControlRoomKernelCommandTransport,
} from '@/features/rooms/kernel/room-kernel-command-transport';
import { evaluateRoomKernelControlGate } from '@/features/rooms/kernel/room-kernel-control-gate';
import { parseSnapshot } from '@/features/rooms/kernel/RoomKernelLivePanel';
import { createPreviewTransport } from './preview-control-transport';

describe('preview control transport', () => {
  it('keeps the Room task view and its stop action on the production contracts', async () => {
    const transport = createPreviewTransport();
    const gate = await evaluateRoomKernelControlGate(await transport.capabilities());
    expect(gate).toMatchObject({ readEnabled: true, commandEnabled: true, panicEnabled: false });

    const raw = await transport.request({
      pathId: 'agent.room.kernel.snapshot',
      params: { roomId: 'room-preview' },
    });
    const snapshot = parseSnapshot(raw, 'room-preview');
    expect(snapshot.roots).toHaveLength(1);
    expect(snapshot.roots[0]).toMatchObject({ state: 'running', owner: '智鼬·此刻' });

    const requirement = parseRoomRequirementsReadProjection(
      record(record(raw).requirementsByRootId)[snapshot.roots[0]!.rootId],
    );
    expect(requirement.anchors[0]?.originalText).toBe('核对多端网关回放与责任闭环');

    const receipt = await createControlRoomKernelCommandTransport(transport).execute(
      buildCancelRootCommand(
        {
          roomId: 'room-preview',
          rootId: snapshot.roots[0]!.rootId,
          generation: snapshot.roots[0]!.generation,
        },
        { commandId: 'preview-stop', sourceId: 'preview-test', createdAtMs: 1 },
      ),
    );
    expect(receipt).toMatchObject({
      commandId: 'preview-stop',
      receiptKind: 'root_cancelled',
      status: 'applied',
      generation: 2,
    });
  });
});

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
