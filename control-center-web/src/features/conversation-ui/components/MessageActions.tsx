import { useState } from 'react';
import type { ReactNode } from 'react';

/** Only the affordances the host can actually honour are rendered; a surface
 *  that cannot fork or rewind shows no dead control. */
export function MessageActions({
  copyLabel = '复制',
  onCopy,
  onEdit,
  onFork,
  onRetry,
  onRewind,
  retryLabel = '重试',
  retryIcon,
  retryPending = false,
  text,
}: {
  text?: string;
  copyLabel?: string;
  retryLabel?: string;
  retryIcon?: ReactNode;
  retryPending?: boolean;
  onCopy?: () => void;
  onEdit?: () => void;
  onRetry?: () => void;
  onFork?: () => void;
  onRewind?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const copyable = Boolean(text && onCopy !== undefined);
  if (!copyable && !onEdit && !onRetry && !onFork && !onRewind) return null;
  const copy = () => {
    if (!text) return;
    void navigator.clipboard?.writeText(text);
    onCopy?.();
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_200);
  };
  return (
    <div aria-label="消息操作" className="ccui-message-actions" role="toolbar">
      {copyable ? <button onClick={copy} type="button">{copied ? '已复制' : copyLabel}</button> : null}
      {onEdit ? <button onClick={onEdit} type="button">编辑</button> : null}
      {onRetry ? <button aria-label={retryPending ? '正在继续' : retryLabel} disabled={retryPending} onClick={onRetry} type="button">{retryIcon}{retryPending ? '正在继续' : retryLabel}</button> : null}
      {onFork ? <button onClick={onFork} type="button">分叉</button> : null}
      {onRewind ? <button onClick={onRewind} type="button">回到这里</button> : null}
    </div>
  );
}
