import { describe, expect, it } from 'vitest';
import { staticHtmlDocument } from './static-html';

describe('static HTML preview', () => {
  it('preserves document layout while removing execution and network surfaces', () => {
    const output = staticHtmlDocument(`
      <html><head>
        <style>.remote { background: url(https://evil.example/a.png) }</style>
        <script>window.top.location='https://evil.example'</script>
      </head><body onload="alert(1)">
        <h1>验收报告</h1>
        <a href="https://evil.example">远程链接</a>
        <a href="#result">页内链接</a>
        <img src="https://evil.example/a.png" onerror="alert(1)">
        <img alt="proof" src="data:image/png;base64,iVBORw0KGgo=">
        <iframe src="https://evil.example"></iframe>
        <form action="https://evil.example"><input name="secret"></form>
      </body></html>
    `);
    const document = new DOMParser().parseFromString(output, 'text/html');

    expect(document.querySelector('h1')?.textContent).toBe('验收报告');
    expect(document.querySelector('script, iframe, form, input')).toBeNull();
    expect(document.body.hasAttribute('onload')).toBe(false);
    expect(document.querySelector('a[href="https://evil.example"]')).toBeNull();
    expect(document.querySelector('a[href="#result"]')).not.toBeNull();
    expect(document.querySelector('img[src^="https:"]')).toBeNull();
    expect(document.querySelector('img[alt="proof"]')?.getAttribute('src')).toBe('data:image/png;base64,iVBORw0KGgo=');
    expect(document.querySelector('style')?.textContent).not.toContain('evil.example');
    expect(document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content'))
      .toContain("script-src 'none'");
  });

  it('replaces media it stripped instead of leaving a broken-image husk', () => {
    const output = staticHtmlDocument('<body><img src="https://tracker.example/p.gif" alt="转化漏斗"><video src="https://evil.example/v.mp4"></video></body>');
    const document = new DOMParser().parseFromString(output, 'text/html');

    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('video')).toBeNull();
    const notes = [...document.querySelectorAll('.rag-ime-blocked-media')].map((node) => node.textContent);
    expect(notes).toContain('已移除远程媒体：转化漏斗');
    expect(notes).toContain('已移除远程媒体');
  });

  it('keeps an inline stylesheet that only styles the document', () => {
    const output = staticHtmlDocument('<head><style>h1{color:#a3341f}table{border-collapse:collapse}</style></head><body><h1>标题</h1></body>');
    const document = new DOMParser().parseFromString(output, 'text/html');

    const authored = [...document.querySelectorAll('style')].map((node) => node.textContent ?? '');
    expect(authored.some((css) => css.includes('#a3341f'))).toBe(true);
  });

  it('drops a link element even when it points at a same-origin stylesheet', () => {
    const output = staticHtmlDocument('<head><link rel="stylesheet" href="/local.css"></head><body>x</body>');
    expect(new DOMParser().parseFromString(output, 'text/html').querySelector('link')).toBeNull();
  });
});
