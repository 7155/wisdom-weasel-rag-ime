import { describe, expect, it } from 'vitest';
import { richHtmlDocument } from './rich-html';

describe('rich HTML preview', () => {
  it('preserves a generated report execution, forms, links, and authored layout', () => {
    const output = richHtmlDocument(`
      <html><head>
        <style>.remote { background: url(https://evil.example/a.png) }</style>
        <script>window.reportReady=true</script>
      </head><body onload="window.loaded=true">
        <h1>验收报告</h1>
        <a href="https://evil.example">远程链接</a>
        <a href="#result">页内链接</a>
        <img src="https://evil.example/a.png" onerror="window.imageFailed=true">
        <img alt="proof" src="data:image/png;base64,iVBORw0KGgo=">
        <iframe src="https://evil.example"></iframe>
        <form action="https://evil.example"><input name="query"></form>
      </body></html>
    `);
    const document = new DOMParser().parseFromString(output, 'text/html');

    expect(document.querySelector('h1')?.textContent).toBe('验收报告');
    expect(document.querySelectorAll('script, iframe, form, input')).toHaveLength(4);
    expect(document.body.hasAttribute('onload')).toBe(true);
    expect(document.querySelector('a[href="https://evil.example"]')).not.toBeNull();
    expect(document.querySelector('a[href="#result"]')).not.toBeNull();
    expect(document.querySelector('img[src^="https:"]')).not.toBeNull();
    expect(document.querySelector('img[alt="proof"]')?.getAttribute('src')).toBe('data:image/png;base64,iVBORw0KGgo=');
    expect([...document.querySelectorAll('style')].some((node) => node.textContent?.includes('evil.example'))).toBe(true);
    expect(document.querySelector('meta[http-equiv="Content-Security-Policy"]')).toBeNull();
  });

  it('keeps authored remote media and stylesheets', () => {
    const output = richHtmlDocument('<head><link rel="stylesheet" href="/local.css"></head><body><img src="https://tracker.example/p.gif" alt="转化漏斗"><video src="https://example.test/v.mp4"></video></body>');
    const document = new DOMParser().parseFromString(output, 'text/html');

    expect(document.querySelector('link')?.getAttribute('href')).toBe('/local.css');
    expect(document.querySelector('img')?.getAttribute('src')).toBe('https://tracker.example/p.gif');
    expect(document.querySelector('video')?.getAttribute('src')).toBe('https://example.test/v.mp4');
  });

  it('keeps authored styles and adds only one host guardrail sheet', () => {
    const output = richHtmlDocument('<head><style>h1{color:#a3341f}</style></head><body><h1>标题</h1></body>');
    const document = new DOMParser().parseFromString(output, 'text/html');

    expect([...document.querySelectorAll('style')].some((node) => node.textContent?.includes('#a3341f'))).toBe(true);
    expect(document.querySelectorAll('style[data-paw-html-host="true"]')).toHaveLength(1);
  });
});
