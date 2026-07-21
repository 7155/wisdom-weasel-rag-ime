import { describe, expect, it } from 'vitest';
import { pairDiffLines, parseUnifiedDiff } from './unified-diff';

describe('unified diff parser', () => {
  it('parses multiple files, line numbers, and no-newline notices', () => {
    const files = parseUnifiedDiff([
      'diff --git a/src/one.ts b/src/one.ts',
      '--- a/src/one.ts',
      '+++ b/src/one.ts',
      '@@ -2,2 +2,2 @@',
      '-const old = true;',
      '+const ready = true;',
      ' keep();',
      '\\ No newline at end of file',
      'diff --git a/src/two.ts b/src/two.ts',
      'new file mode 100644',
      '--- /dev/null',
      '+++ b/src/two.ts',
      '@@ -0,0 +1 @@',
      '+export {};',
    ].join('\n'));

    expect(files).toHaveLength(2);
    expect(files[0]).toMatchObject({ path: 'src/one.ts', status: 'modified' });
    expect(files[0]?.hunks[0]?.lines).toEqual([
      { kind: 'remove', content: 'const old = true;', oldLine: 2, newLine: null },
      { kind: 'add', content: 'const ready = true;', oldLine: null, newLine: 2 },
      { kind: 'context', content: 'keep();', oldLine: 3, newLine: 3 },
      { kind: 'notice', content: 'No newline at end of file', oldLine: null, newLine: null },
    ]);
    expect(files[1]).toMatchObject({ path: 'src/two.ts', status: 'added' });
  });

  it('supports patches without git headers plus deleted and renamed files', () => {
    const plain = parseUnifiedDiff('--- a/old.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone');
    expect(plain[0]).toMatchObject({ path: 'old.txt', status: 'deleted' });

    const renamed = parseUnifiedDiff([
      'diff --git a/old.md b/new.md',
      'similarity index 100%',
      'rename from old.md',
      'rename to new.md',
    ].join('\n'));
    expect(renamed[0]).toMatchObject({ oldPath: 'old.md', newPath: 'new.md', path: 'new.md', status: 'renamed' });
  });

  it('pairs adjacent removals and additions for split rendering', () => {
    const lines = parseUnifiedDiff('--- a/a\n+++ b/a\n@@ -1,2 +1,2 @@\n-one\n-two\n+three\n context')[0]!.hunks[0]!.lines;
    const pairs = pairDiffLines(lines);
    expect(pairs).toHaveLength(3);
    expect(pairs[0]).toMatchObject({ left: { content: 'one' }, right: { content: 'three' } });
    expect(pairs[1]).toMatchObject({ left: { content: 'two' }, right: null });
    expect(pairs[2]?.left).toBe(pairs[2]?.right);
  });
});
