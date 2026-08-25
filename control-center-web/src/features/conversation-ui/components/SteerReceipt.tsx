import React from "react";
import type { SteerReceiptState } from "../model/types";

export function SteerReceipt({
  state,
  timestamp,
  canInterrupt,
  onInterrupt,
  onCancelAndEdit,
}: {
  state: SteerReceiptState;
  timestamp: number;
  canInterrupt: boolean;
  onInterrupt?(): void;
  onCancelAndEdit?(): void;
}) {
  if (state === "done") {
    return <time className="ccui-receipt-time">{new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>;
  }
  if (state === "settling") {
    return <time className="ccui-receipt-time ccui-fade-in">{new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>;
  }
  return (
    <div className="ccui-steer-receipt" role="status" aria-live="polite">
      {!canInterrupt ? <span>{state}</span> : null}
      {state === "unread" && canInterrupt && onInterrupt ? (
        <button className="ccui-text-action" type="button" onClick={onInterrupt} title="Ends the current step so this message is read next">
          Interrupt
        </button>
      ) : null}
      {state === "unread" && onCancelAndEdit ? (
        <button className="ccui-icon-action" type="button" onClick={onCancelAndEdit} aria-label="Cancel and edit message">×</button>
      ) : null}
      {state === "read" ? <span>read</span> : null}
    </div>
  );
}
