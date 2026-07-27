import { useMemo, useState } from 'react';
import { Columns2, Rows3 } from 'lucide-react';
import { SegmentedControl } from '@/components/primitives';
import { pairDiffLines, parseUnifiedDiff, type DiffFile, type DiffLine } from './unified-diff';

export function DiffPreview({ content, fileName = '' }: { content: string; fileName?: string }) {
  const [mode, setMode] = useState<'unified' | 'split'>('unified');
  const files = useMemo(() => {
    const parsed = parseUnifiedDiff(content);
    if (parsed.length || !fileName || !content.trimStart().startsWith('@@')) return parsed;
    /* Agent blocks often already carry the path separately and therefore send
       only hunks. The preview parser correctly rejects that as a standalone
       patch, but rendering it as undifferentiated preformatted text loses the
       actual change. Reattach the trusted display path locally; no contract or
       file content is changed. */
    return parseUnifiedDiff(`--- a/${fileName}\n+++ b/${fileName}\n${content}`);
  }, [content, fileName]);
  if (!files.length) {
    return <pre className="agent-file-preview__plain"><code>{content || '没有可展示的变更。'}</code></pre>;
  }
  return (
    <div className="agent-diff-preview">
      <header>
        <small>{files.length} 个文件</small>
        <SegmentedControl
          aria-label="Diff 展示方式"
          className="agent-diff-preview__mode"
          items={[
            { value: 'unified', label: <span><Rows3 size={13} />单栏</span> },
            { value: 'split', label: <span><Columns2 size={13} />并排</span> },
          ]}
          onValueChange={setMode}
          value={mode}
        />
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
