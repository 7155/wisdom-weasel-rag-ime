/** Build one complete document for model-authored and generated HTML results.
 *
 * The source is the deliverable. Do not run it through the generic text/file
 * sanitizer: doing so silently removes charts, forms, scripts, linked styles,
 * and other content the report needs to render. Isolation belongs to the
 * iframe sandbox, while this function only adds host layout guardrails.
 */
export const RICH_HTML_SANDBOX = 'allow-downloads allow-forms allow-modals allow-pointer-lock allow-popups allow-scripts';

export const RICH_HTML_PREVIEW_PATH = '/__paw_html_preview';

/**
 * Put authored HTML in the URL fragment of a dedicated loopback document.
 * Fragments never cross the HTTP boundary. The document served by 8766 owns a
 * narrow preview-only CSP and an opaque sandbox, so authored scripts can run
 * without relaxing the Control Center's CSP or sharing its origin.
 */
export function richHtmlPreviewUrl(source: string): string {
  const bytes = new TextEncoder().encode(source);
  let binary = '';
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  const encoded = window.btoa(binary)
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replace(/=+$/u, '');
  return `${RICH_HTML_PREVIEW_PATH}#${encoded}`;
}

export function richHtmlDocument(source: string): string {
  const completeDocument = /(?:<!doctype\s+html\b|<html\b|<head\b|<body\b)/iu.test(source);
  const document = new DOMParser().parseFromString(
    completeDocument ? source : `<main class="paw-html-fragment">${source}</main>`,
    'text/html',
  );

  if (!document.head.querySelector('meta[name="viewport"]')) {
    const viewport = document.createElement('meta');
    viewport.name = 'viewport';
    viewport.content = 'width=device-width, initial-scale=1';
    document.head.prepend(viewport);
  }

  const guardrails = document.createElement('style');
  guardrails.dataset.pawHtmlHost = 'true';
  guardrails.textContent = [
    'html{box-sizing:border-box;min-width:0}',
    '*,*::before,*::after{box-sizing:inherit}',
    'body{min-width:0;margin:0;overflow-wrap:anywhere}',
    '.paw-html-fragment{padding:18px;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17231d;background:#fff}',
    'img,video,svg,canvas{max-width:100%}',
    'pre,table{max-width:100%;overflow:auto}',
  ].join('');
  document.head.append(guardrails);
  return `<!doctype html>${document.documentElement.outerHTML}`;
}
