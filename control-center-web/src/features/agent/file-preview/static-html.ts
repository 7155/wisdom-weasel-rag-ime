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

  const policy = document.createElement('meta');
  policy.httpEquiv = 'Content-Security-Policy';
  policy.content = CSP;
  const viewport = document.createElement('meta');
  viewport.name = 'viewport';
  viewport.content = 'width=device-width, initial-scale=1';
  const baseStyle = document.createElement('style');
  baseStyle.textContent = 'html{color-scheme:light}body{box-sizing:border-box;max-width:960px;margin:0 auto;padding:24px;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17231d;background:#fff}img{max-width:100%;height:auto}pre{overflow:auto;padding:12px;background:#f3f6f4}table{max-width:100%;border-collapse:collapse}th,td{padding:6px 8px;border:1px solid #ccd6d0}';
  document.head.prepend(baseStyle);
  document.head.prepend(viewport);
  document.head.prepend(policy);
  return `<!doctype html>${document.documentElement.outerHTML}`;
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
