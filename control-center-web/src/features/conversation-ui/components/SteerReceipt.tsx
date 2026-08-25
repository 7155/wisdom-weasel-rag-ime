import type { SteerReceiptState } from '../model/types';

/**
 * A steering message is delivered before the agent has read it, so the receipt
 * is the only honest place to say so — and the only place where cancelling is
 * still free. Once the agent has read it, the receipt settles back into a
 * plain timestamp instead of leaving a control on a settled turn.
 */
export function SteerReceipt({
  canInterrupt,
  clock,
  onCancelAndEdit,
  onInterrupt,
  state,
  timestamp,
}: {
  state: SteerReceiptState;
  timestamp: number;
  canInterrupt: boolean;
  clock(timestamp: number): string;
  onInterrupt?(): void;
  onCancelAndEdit?(): void;
}) {
  if (state === 'done' || state === 'settling') {
    return <time className={`ccui-receipt-time${state === 'settling' ? ' ccui-fade-in' : ''}`}>{clock(timestamp)}</time>;
  }
  return (
    <div aria-live="polite" className="ccui-steer-receipt" data-receipt={state} role="status">
      {/* Delivery is what a host can actually prove; claiming a partner has
          read the message would put a promise on the transcript. */}
      <span>{state === 'read' ? '已送达伙伴' : '尚未送达伙伴'}</span>
      {state === 'unread' && canInterrupt && onInterrupt ? (
        <button
          className="ccui-text-action"
          onClick={onInterrupt}
          title="结束当前步骤，让这条消息被下一个读到"
          type="button"
        >打断当前步骤</button>
      ) : null}
      {state === 'unread' && onCancelAndEdit ? (
        <button aria-label="撤回并重新编辑这条消息" className="ccui-icon-action" onClick={onCancelAndEdit} type="button">×</button>
      ) : null}
    </div>
  );
}
