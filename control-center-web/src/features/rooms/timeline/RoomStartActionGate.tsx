import { LoaderCircle, Play } from 'lucide-react';

import { Button } from '@/components/primitives';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { RootProjection } from '@/contracts/room-kernel-reducer';

function authoritativeRootReceipts(
  root: RootProjection | undefined,
  receipts: readonly RoomKernelReceiptV1[],
): RoomKernelReceiptV1[] {
  if (!root) return [];
  return receipts.filter((receipt) => (
    receipt.rootId === root.rootId
    && receipt.generation === root.generation
    && receipt.status === 'applied'
  ));
}

export function roomRootIntakePhase(
  root: RootProjection | undefined,
  receipts: readonly RoomKernelReceiptV1[],
): string {
  const latestIntake = authoritativeRootReceipts(root, receipts)
    .filter((receipt) => receipt.details.purpose === 'intake_phase')
    .sort((left, right) => (
      right.createdAtMs - left.createdAtMs
      || right.receiptId.localeCompare(left.receiptId)
    ))[0];
  return typeof latestIntake?.details.phase === 'string'
    ? latestIntake.details.phase
    : '';
}

export function roomRootRequiresStartAction(
  root: RootProjection | undefined,
  receipts: readonly RoomKernelReceiptV1[],
): boolean {
  if (!root || root.state !== 'waiting') return false;
  const authoritative = authoritativeRootReceipts(root, receipts);
  const definition = [...authoritative]
    .filter((receipt) => receipt.details.operation === 'room_define')
    .sort((left, right) => (
      right.createdAtMs - left.createdAtMs
      || right.receiptId.localeCompare(left.receiptId)
    ))[0];
  if (definition?.details.requiresStartAction !== true) return false;
  return roomRootIntakePhase(root, authoritative) === 'awaiting_start';
}

export function RoomStartActionGate({
  onStart,
  starting,
}: {
  onStart: () => void;
  starting: boolean;
}) {
  return <div aria-label="确认开始行动" className="room-start-action" role="group">
    <span>现在开始行动吗？</span>
    <Button
      disabled={starting}
      leadingIcon={starting ? <LoaderCircle className="ui-spin" size={14} /> : <Play size={14} />}
      onClick={onStart}
      variant="primary"
    >{starting ? '正在开始' : '开始行动'}</Button>
  </div>;
}
