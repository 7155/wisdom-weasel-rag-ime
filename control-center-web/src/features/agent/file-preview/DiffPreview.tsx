import { useMemo, useState } from 'react';
import { SegmentedControl } from '@/components/primitives';
import { pairDiffLines, parseUnifiedDiff, type DiffFile, type DiffLine } from './unified-diff';

export function DiffPreview({ content }: { content: string }) {
  const [mode, setMode] = useState<'unified' | 'split'>('unified');
  const files = useMemo(() => parseUnifiedDiff(content), [content]);
  if (!files.length) {
    return <pre className="agent-file-preview__plain"><code>{content || '没有可展示的变更。'}</code></pre>;
  }
  return (
    <div className="agent-diff-preview">
      <header>
        <SegmentedControl
          aria-label="Diff 展示方式"
          items={[{ value: 'unified', label: '统一' }, { value: 'split', label: '并排' }]}
          onValueChange={setMode}
          value={mode}
        />
        <small>{files.length} 个文件</small>
      </header>
      <div className="agent-diff-preview__files">
        {files.map((file, index) => <FileDiff key={`${file.path}:${index}`} file={file} mode={mode} />)}
      </div>
    </div>
  );
}

function FileDiff({ file, mode }: { file: DiffFile; mode: 'unified' | 'split' }) {
  return (
    <section className="agent-diff-file" data-status={file.status}>
      <header><strong>{file.path}</strong><span>{statusLabel(file.status)}</span></header>
      <div className="agent-diff-file__scroll">
        {file.hunks.map((hunk, index) => (
          <div className="agent-diff-hunk" key={`${hunk.header}:${index}`}>
            <div className="agent-diff-hunk__header">{hunk.header}</div>
            {mode === 'unified' ? <UnifiedLines lines={hunk.lines} /> : <SplitLines lines={hunk.lines} />}
          </div>
        ))}
      </div>
    </section>
  );
}

function UnifiedLines({ lines }: { lines: readonly DiffLine[] }) {
  return <table><tbody>{lines.map((line, index) => (
    <tr data-kind={line.kind} key={index}>
      <td className="agent-diff-gutter">{line.oldLine ?? ''}</td>
      <td className="agent-diff-gutter">{line.newLine ?? ''}</td>
      <td className="agent-diff-code"><span>{prefix(line.kind)}</span>{line.content}</td>
    </tr>
  ))}</tbody></table>;
}

function SplitLines({ lines }: { lines: readonly DiffLine[] }) {
  return <table><tbody>{pairDiffLines(lines).map((pair, index) => (
    <tr key={index}>
      <SplitCell line={pair.left} side="left" />
      <SplitCell line={pair.right} side="right" />
    </tr>
  ))}</tbody></table>;
}

function SplitCell({ line, side }: { line: DiffLine | null; side: 'left' | 'right' }) {
  const lineNumber = side === 'left' ? line?.oldLine : line?.newLine;
  return (
    <td className="agent-diff-split" data-empty={!line || undefined} data-kind={line?.kind}>
      <span className="agent-diff-gutter">{lineNumber ?? ''}</span>
      <code>{line?.content ?? ''}</code>
    </td>
  );
}

function prefix(kind: DiffLine['kind']): string {
  if (kind === 'add') return '+';
  if (kind === 'remove') return '-';
  return ' ';
}

function statusLabel(status: DiffFile['status']): string {
  return ({ modified: '修改', added: '新增', deleted: '删除', renamed: '重命名' })[status];
}
