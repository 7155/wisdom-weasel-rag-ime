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
});
