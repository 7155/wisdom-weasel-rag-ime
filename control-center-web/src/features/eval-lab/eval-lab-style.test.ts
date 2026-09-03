import { describe, expect, it } from 'vitest';
import evalLabCss from './eval-lab.css?raw';

describe('Agent Lab embedded Room layout', () => {
  it('gives the Room workspace a definite block size so its transcript can scroll', () => {
    const rule = evalLabCss.match(/\.eval-lab__room-workspace\s*\{([^}]*)\}/s)?.[1] ?? '';
    expect(rule).toMatch(/(?:^|;)\s*height:\s*520px;/);
    expect(rule).toMatch(/(?:^|;)\s*overflow:\s*hidden;/);
  });
});
