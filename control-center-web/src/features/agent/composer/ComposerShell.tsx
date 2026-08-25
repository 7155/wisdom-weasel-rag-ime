import { Paperclip, X } from 'lucide-react';
import type { MouseEvent, ReactNode, RefObject } from 'react';

export interface ComposerShellAttachment {
  id: string;
  name: string;
  /** Owner-provided thumbnail; the shell falls back to a paperclip glyph. */
  preview?: ReactNode;
  /** Owner-specific accessible remove label; defaults to `移除 ${name}`. */
  removeLabel?: string;
}

/**
 * UR-042: 新建、Session 与 Room 共用这一个 Composer 骨架。
 *
 * The shell owns the shared skeleton only — the framed `.agent-composer`
 * surface, the attachment strip, the textarea slot, the toolbar rows, and the
 * click-anywhere-to-focus behavior. Session/Room differences remain control
 * content passed through `banner`/`controls`/`actions`; they never become a
 * second Composer skin.
 */
export function ComposerShell({
  actions,
  attachments = [],
  attachmentsLabel = '待发送附件',
  banner,
  busy = false,
  children,
  className = '',
  controls,
  focusRef,
  jumpLatest = false,
  onRemoveAttachment,
}: {
  actions?: ReactNode;
  attachments?: readonly ComposerShellAttachment[];
  attachmentsLabel?: string;
  banner?: ReactNode;
  busy?: boolean;
  /** The owning composer's textarea (each owner keeps its own IME/keys). */
  children: ReactNode;
  className?: string;
  controls?: ReactNode;
  focusRef: RefObject<HTMLTextAreaElement | null>;
  jumpLatest?: boolean;
  onRemoveAttachment?: (id: string) => void;
}) {
  // The dock is taller than its text line — clicks that land on chrome rather
  // than on a real control put the caret back in the message, which is what
  // the one-input surface visually promises.
  function redirectFocus(event: MouseEvent<HTMLDivElement>): void {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('button, a, input, textarea, select, [role="radiogroup"], [contenteditable]')) return;
    event.preventDefault();
    focusRef.current?.focus();
  }
  return (
    <div
      className={`agent-composer paw-unified-composer${className ? ` ${className}` : ''}`}
      data-busy={busy || undefined}
      data-jump-latest={jumpLatest || undefined}
      onMouseDown={redirectFocus}
    >
      {banner}
      {attachments.length ? (
        <div className="agent-composer__attachments" aria-label={attachmentsLabel} role="list">
          {attachments.map((attachment) => (
            <span className="agent-composer__attachment-chip" key={attachment.id} role="listitem">
              {attachment.preview ?? <Paperclip aria-hidden="true" size={16} />}
              <b title={attachment.name}>{attachment.name}</b>
              <button
                type="button"
                aria-label={attachment.removeLabel ?? `移除 ${attachment.name}`}
                onClick={() => onRemoveAttachment?.(attachment.id)}
              ><X size={12} /></button>
            </span>
          ))}
        </div>
      ) : null}
      {children}
      <div className="agent-composer__toolbar">
        <div className="agent-composer__controls">{controls}</div>
        <div className="agent-composer__actions">{actions}</div>
      </div>
    </div>
  );
}
