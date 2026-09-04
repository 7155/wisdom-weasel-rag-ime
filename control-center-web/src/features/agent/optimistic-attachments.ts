const PENDING_CLIPBOARD_ATTACHMENT_ID = 'pending-clipboard-image';
const HOME_ATTACHMENT_ID_PREFIX = 'home-attachment-';

/** Local attachment ids exist only while Home imports bytes into managed
 * media. They are never valid Runtime media ids and must not be replayed. */
export function isUndurableAgentAttachmentId(value: string): boolean {
  return value === PENDING_CLIPBOARD_ATTACHMENT_ID
    || value.startsWith(HOME_ATTACHMENT_ID_PREFIX);
}

export function hasUndurableAgentAttachments(values: readonly string[]): boolean {
  return values.some(isUndurableAgentAttachmentId);
}
