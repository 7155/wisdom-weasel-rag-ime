import { describe, expect, it } from 'vitest';
import knowledgeCss from './knowledge.css?raw';

// Same contract as the Agent readers: raw/code surfaces always pair the shared
// code tokens so code never renders light-on-light or dark-on-dark.
describe('knowledge code surface ownership', () => {
  it('keeps the Markdown code reader on the shared paired code tokens', () => {
    expect(knowledgeCss).toMatch(
      /\.knowledge-markdown-body pre\s*\{[^}]*background:\s*var\(--color-code-bg\);[^}]*color:\s*var\(--color-code-text\);[^}]*\}/s,
    );
  });

  it('never sets the code background without the paired code text colour', () => {
    for (const rule of knowledgeCss.split('}')) {
      if (rule.includes('--color-code-bg')) {
        expect(rule).toContain('var(--color-code-text)');
      }
    }
  });
});
