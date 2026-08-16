import { useLayoutEffect, useState } from 'react';

/**
 * The Control Center CSP deliberately allows framed documents through blob:
 * URLs. WebKit does not consistently treat about:srcdoc as that source, which
 * made the same report work in Chromium tests but render as a white frame in
 * the native host. Keep the authored document intact and move only its
 * transport to the CSP-owned blob channel.
 */
export function useRichHtmlUrl(document: string, enabled = true): string {
  const [url, setUrl] = useState('');
  useLayoutEffect(() => {
    if (!enabled || typeof URL.createObjectURL !== 'function') {
      setUrl('');
      return undefined;
    }
    const next = URL.createObjectURL(new Blob([document], { type: 'text/html;charset=utf-8' }));
    setUrl(next);
    return () => {
      URL.revokeObjectURL(next);
    };
  }, [document, enabled]);
  return url;
}
