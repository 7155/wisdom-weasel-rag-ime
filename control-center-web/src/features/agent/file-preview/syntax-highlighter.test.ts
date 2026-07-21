import { describe, expect, it } from 'vitest';
import { highlightCode } from './syntax-highlighter';

describe('syntax highlighter', () => {
  it('loads a bounded known grammar and keeps unknown languages on the plain-text path', async () => {
    expect(await highlightCode('const ready: boolean = true;', 'ts')).toContain('shiki');
    expect(await highlightCode('opaque', 'not-a-real-language')).toBe('');
  });
});
