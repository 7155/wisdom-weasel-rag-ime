const BLOCKED_ELEMENTS = [
  'script', 'noscript', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet',
  'form', 'input', 'button', 'textarea', 'select', 'option', 'link', 'base', 'meta',
  'portal', 'foreignObject',
];
const URL_ATTRIBUTES = new Set(['href', 'src', 'srcset', 'poster', 'action', 'formaction', 'xlink:href']);
const SAFE_DATA_IMAGE = /^data:image\/(?:png|jpeg|gif|webp);base64,[a-z0-9+/=]+$/iu;
const CSP = "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:; media-src data: blob:; connect-src 'none'; script-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";

export function staticHtmlDocument(source: string): string {
  const document = new DOMParser().parseFromString(source, 'text/html');
  for (const selector of BLOCKED_ELEMENTS) {
    document.querySelectorAll(selector).forEach((element) => element.remove());
  }
  document.querySelectorAll('*').forEach((element) => sanitizeElement(element));
  replaceStrippedMedia(document);

  const policy = document.createElement('meta');
  policy.httpEquiv = 'Content-Security-Policy';
  policy.content = CSP;
  const viewport = document.createElement('meta');
  viewport.name = 'viewport';
  viewport.content = 'width=device-width, initial-scale=1';
  const baseStyle = document.createElement('style');
  /* The document keeps the appearance its author gave it — this is their page,
     not our surface — so the base sheet only supplies fallbacks and guardrails:
     a readable measure, media that cannot overflow, and a visible marker where
     something was removed. */
  baseStyle.textContent = [
    'html{color-scheme:light}',
    'body{box-sizing:border-box;max-width:960px;margin:0 auto;padding:24px 24px 40px;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17231d;background:#fff}',
    'img,video{max-width:100%;height:auto}',
    'pre{overflow:auto;padding:12px;background:#f3f6f4}',
    'table{max-width:100%;border-collapse:collapse}',
    'th,td{padding:6px 8px;border:1px solid #ccd6d0}',
    '.rag-ime-blocked-media{display:inline-block;padding:2px 7px;border:1px dashed #b9c4be;border-radius:3px;background:#f4f6f5;color:#5c665f;font-size:13px;font-style:italic}',
  ].join('');
  document.head.prepend(baseStyle);
  document.head.prepend(viewport);
  document.head.prepend(policy);
  return `<!doctype html>${document.documentElement.outerHTML}`;
}

/**
 * Stripping a remote src leaves the element behind, and the browser then draws
 * its broken-image glyph — the report ends up looking damaged rather than
 * protected. Replacing the husk with a labelled note says plainly what happened
 * and keeps the author's alt text, which is usually the caption a reader needs.
 */
function replaceStrippedMedia(document: Document): void {
  for (const element of document.querySelectorAll('img:not([src]), video:not([src]), audio:not([src]), source:not([src])')) {
    const note = document.createElement('span');
    note.className = 'rag-ime-blocked-media';
    const alt = element.getAttribute('alt')?.trim();
    note.textContent = alt ? `已移除远程媒体：${alt}` : '已移除远程媒体';
    element.replaceWith(note);
  }
}

function sanitizeElement(element: Element): void {
  for (const attribute of [...element.attributes]) {
    const name = attribute.name.toLowerCase();
    const value = attribute.value.trim();
    if (name.startsWith('on') || name === 'srcdoc' || name === 'target' || URL_ATTRIBUTES.has(name)) {
      if (name === 'href' && value.startsWith('#')) continue;
      if (name === 'src' && SAFE_DATA_IMAGE.test(value)) continue;
      element.removeAttribute(attribute.name);
      continue;
    }
    if (name === 'style' && unsafeCss(value)) element.removeAttribute(attribute.name);
  }
  if (element.tagName.toLowerCase() === 'style' && unsafeCss(element.textContent ?? '')) {
    element.remove();
  }
}

function unsafeCss(value: string): boolean {
  return /(?:@import|url\s*\(|expression\s*\(|-moz-binding)/iu.test(value);
}
