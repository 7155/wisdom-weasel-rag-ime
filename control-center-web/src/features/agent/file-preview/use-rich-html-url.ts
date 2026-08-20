import { useMemo } from 'react';
import { richHtmlPreviewUrl } from './rich-html';

/**
 * The preview is a dedicated loopback document rather than srcdoc/blob/data.
 * Those local documents inherit the Control Center CSP and therefore cannot
 * execute authored inline scripts. The loopback document has its own
 * preview-only CSP and is still isolated by an opaque iframe sandbox.
 */
export function useRichHtmlUrl(document: string, enabled = true): string {
  return useMemo(() => (enabled ? richHtmlPreviewUrl(document) : ''), [document, enabled]);
}
