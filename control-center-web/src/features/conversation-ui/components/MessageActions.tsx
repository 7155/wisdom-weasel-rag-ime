import React, { useState } from "react";

export function MessageActions({
  text,
  onEdit,
  onRetry,
  onFork,
  onRewind,
}: {
  text?: string;
  onEdit?: () => void;
  onRetry?: () => void;
  onFork?: () => void;
  onRewind?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!text) return;
    await navigator.clipboard?.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className="ccui-message-actions" role="toolbar" aria-label="Message actions">
      {text ? <button type="button" onClick={copy} title="Copy">{copied ? "Copied" : "Copy"}</button> : null}
      {onEdit ? <button type="button" onClick={onEdit}>Edit</button> : null}
      {onRetry ? <button type="button" onClick={onRetry}>Retry</button> : null}
      {onFork ? <button type="button" onClick={onFork}>Fork</button> : null}
      {onRewind ? <button type="button" onClick={onRewind}>Rewind</button> : null}
    </div>
  );
}
