import { CheckCircle2, LoaderCircle, Play } from 'lucide-react';

import { Button } from '@/components/primitives';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { RootProjection } from '@/contracts/room-kernel-reducer';

export function roomRootRequiresStartAction(
  root: RootProjection | undefined,
  receipts: readonly RoomKernelReceiptV1[],
): boolean {
  if (!root || root.state !== 'waiting') return false;
  const authoritative = receipts.filter((receipt) => (
    receipt.rootId === root.rootId
    && receipt.generation === root.generation
    && receipt.status === 'applied'
  ));
  const definition = [...authoritative]
    .filter((receipt) => receipt.details.operation === 'room_define')
    .sort((left, right) => (
      right.createdAtMs - left.createdAtMs
      || right.receiptId.localeCompare(left.receiptId)
    ))[0];
  if (definition?.details.requiresStartAction !== true) return false;
  const latestIntake = [...authoritative]
    .filter((receipt) => receipt.details.purpose === 'intake_phase')
    .sort((left, right) => (
      right.createdAtMs - left.createdAtMs
      || right.receiptId.localeCompare(left.receiptId)
    ))[0];
  return Boolean(
    latestIntake
    && latestIntake.details.phase === 'awaiting_start'
    && latestIntake.details.clarificationOccurred === true,
  );
}

export function RoomStartActionGate({
  onStart,
  starting,
}: {
  onStart: () => void;
  starting: boolean;
}) {
  return <section aria-label="确认开始行动" className="room-start-action-gate" role="status">
    <span className="room-start-action-gate__icon" aria-hidden="true">
      <CheckCircle2 size={16} />
    </span>
    <span>
      <strong>目标、交付和边界已经对齐</strong>
      <small>刚才的澄清改变了执行条件。由你确认后，伙伴才会开始已对齐的任务。</small>
    </span>
    <Button
      disabled={starting}
      leadingIcon={starting ? <LoaderCircle className="ui-spin" size={14} /> : <Play size={14} />}
      onClick={onStart}
      size="small"
      variant="primary"
    >{starting ? '正在开始' : '开始行动'}</Button>
  </section>;
}
