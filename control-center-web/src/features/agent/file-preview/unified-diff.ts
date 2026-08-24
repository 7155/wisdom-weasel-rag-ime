export type DiffLineKind = 'add' | 'remove' | 'context' | 'notice';

export interface DiffLine {
  kind: DiffLineKind;
  content: string;
  oldLine: number | null;
  newLine: number | null;
}

export interface DiffHunk {
  header: string;
  oldStart: number;
  newStart: number;
  lines: DiffLine[];
}

export interface DiffFile {
  oldPath: string;
  newPath: string;
  path: string;
  status: 'modified' | 'added' | 'deleted' | 'renamed';
  hunks: DiffHunk[];
}

const MAX_DIFF_LINES = 12_000;

export function parseUnifiedDiff(source: string): DiffFile[] {
  const files: DiffFile[] = [];
  let current: DiffFile | null = null;
  let hunk: DiffHunk | null = null;
  let oldLine = 0;
  let newLine = 0;
  let consumedLines = 0;

  for (const line of source.replace(/\r\n?/gu, '\n').split('\n')) {
    if (consumedLines >= MAX_DIFF_LINES) break;
    const gitHeader = /^diff --git (.+) (.+)$/u.exec(line);
    if (gitHeader) {
      current = createFile(cleanPatchPath(gitHeader[1] ?? ''), cleanPatchPath(gitHeader[2] ?? ''));
      files.push(current);
      hunk = null;
      continue;
    }

    if (line.startsWith('--- ')) {
      const oldPath = cleanPatchPath(line.slice(4).split('\t', 1)[0] ?? '');
      if (!current || current.hunks.length > 0) {
        current = createFile(oldPath, '');
        files.push(current);
      } else {
        current.oldPath = oldPath;
      }
      current.status = oldPath === '/dev/null' ? 'added' : current.status;
      hunk = null;
      continue;
    }

    if (line.startsWith('+++ ')) {
      const newPath = cleanPatchPath(line.slice(4).split('\t', 1)[0] ?? '');
      if (!current) {
        current = createFile('', newPath);
        files.push(current);
      }
      current.newPath = newPath;
      current.path = displayPath(current.oldPath, newPath);
      current.status = newPath === '/dev/null' ? 'deleted' : current.oldPath === '/dev/null' ? 'added' : current.status;
      continue;
    }

    if (!current) continue;
    if (line.startsWith('rename from ')) {
      current.oldPath = cleanPatchPath(line.slice('rename from '.length));
      current.status = 'renamed';
      continue;
    }
    if (line.startsWith('rename to ')) {
      current.newPath = cleanPatchPath(line.slice('rename to '.length));
      current.path = current.newPath;
      current.status = 'renamed';
      continue;
    }
    if (line.startsWith('new file mode ')) {
      current.status = 'added';
      continue;
    }
    if (line.startsWith('deleted file mode ')) {
      current.status = 'deleted';
      continue;
    }

    const header = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$/u.exec(line);
    if (header) {
      oldLine = Number(header[1]);
      newLine = Number(header[3]);
      hunk = { header: line, oldStart: oldLine, newStart: newLine, lines: [] };
      current.hunks.push(hunk);
      continue;
    }
    if (!hunk) continue;

    if (line.startsWith('\\ No newline at end of file')) {
      hunk.lines.push({ kind: 'notice', content: line.slice(2), oldLine: null, newLine: null });
    } else if (line.startsWith('+')) {
      hunk.lines.push({ kind: 'add', content: line.slice(1), oldLine: null, newLine: newLine++ });
    } else if (line.startsWith('-')) {
      hunk.lines.push({ kind: 'remove', content: line.slice(1), oldLine: oldLine++, newLine: null });
    } else if (line.startsWith(' ') || line === '') {
      hunk.lines.push({ kind: 'context', content: line ? line.slice(1) : '', oldLine: oldLine++, newLine: newLine++ });
    } else {
      continue;
    }
    consumedLines += 1;
  }

  return files.filter((file) => file.hunks.length > 0 || file.status === 'renamed');
}

export interface DiffLineTotals {
  added: number;
  removed: number;
}

export function countFileDiffLines(file: DiffFile): DiffLineTotals {
  const totals: DiffLineTotals = { added: 0, removed: 0 };
  for (const hunk of file.hunks) {
    for (const line of hunk.lines) {
      if (line.kind === 'add') totals.added += 1;
      else if (line.kind === 'remove') totals.removed += 1;
    }
  }
  return totals;
}

export function countDiffLines(files: readonly DiffFile[]): DiffLineTotals {
  return files.reduce<DiffLineTotals>((totals, file) => {
    const fileTotals = countFileDiffLines(file);
    return { added: totals.added + fileTotals.added, removed: totals.removed + fileTotals.removed };
  }, { added: 0, removed: 0 });
}

export function pairDiffLines(lines: readonly DiffLine[]): Array<{ left: DiffLine | null; right: DiffLine | null }> {
  const pairs: Array<{ left: DiffLine | null; right: DiffLine | null }> = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index]!;
    if (line.kind === 'context' || line.kind === 'notice') {
      pairs.push({ left: line, right: line });
      index += 1;
      continue;
    }
    const removed: DiffLine[] = [];
    const added: DiffLine[] = [];
    while (lines[index]?.kind === 'remove') removed.push(lines[index++]!);
    while (lines[index]?.kind === 'add') added.push(lines[index++]!);
    const length = Math.max(removed.length, added.length);
    for (let offset = 0; offset < length; offset += 1) {
      pairs.push({ left: removed[offset] ?? null, right: added[offset] ?? null });
    }
  }
  return pairs;
}

function createFile(oldPath: string, newPath: string): DiffFile {
  return {
    oldPath,
    newPath,
    path: displayPath(oldPath, newPath),
    status: oldPath === '/dev/null' ? 'added' : newPath === '/dev/null' ? 'deleted' : 'modified',
    hunks: [],
  };
}

function cleanPatchPath(value: string): string {
  const unquoted = value.trim().replace(/^"|"$/gu, '');
  if (unquoted === '/dev/null') return unquoted;
  return unquoted.replace(/^[ab]\//u, '');
}

function displayPath(oldPath: string, newPath: string): string {
  if (newPath && newPath !== '/dev/null') return newPath;
  if (oldPath && oldPath !== '/dev/null') return oldPath;
  return '未命名变更';
}
