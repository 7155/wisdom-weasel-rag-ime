import { describe, expect, it } from 'vitest';
import { highlightCode } from './syntax-highlighter';

describe('syntax highlighter', () => {
  it('loads a bounded known grammar and keeps unknown languages on the plain-text path', async () => {
    expect(await highlightCode('const ready: boolean = true;', 'ts')).toContain('shiki');
    expect(await highlightCode('opaque', 'not-a-real-language')).toBe('');
  });

  it('lets a conversation reader keep the paired code surface by stripping the inline root colours', async () => {
    const owned = await highlightCode('const ready: boolean = true;', 'ts', { inheritSurface: true });
    expect(owned).toContain('shiki');
    expect(owned).not.toMatch(/<pre[^>]*style=/);
    // Token spans keep their escaped palette; only the root surface is ceded.
    expect(owned).toMatch(/<span[^>]*style="color:/);
    expect(owned).toContain('--shiki-light:');
  });
});
