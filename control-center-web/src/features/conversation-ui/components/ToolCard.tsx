import { useState, type ReactNode } from 'react';
import type { ToolCallBlock } from '../model/types';

const TOOL_STATUS_LABEL: Record<ToolCallBlock['status'], string> = {
  pending: '等待',
  running: '正在执行',
  success: '已完成',
  error: '失败',
  cancelled: '已停止',
};

/** One tool call as a bounded receipt: a reader line always, the raw call and
 *  its evidence one click away. Folding is presentation only — the detail the
 *  host hands over is the same Runtime trace, never a summary of it. */
export function ToolCard({ action, block, detail }: {
  block: ToolCallBlock;
  /** Always-visible host action (a pending approval must never fold away). */
  action?: ReactNode;
  /** Host-rendered body inside the disclosure; supersedes the model output,
   *  which exists so a host without structured evidence still shows one. */
  detail?: ReactNode;
}) {
  const [open, setOpen] = useState(block.status === 'error');
  const hasDetail = Boolean(block.input || block.output || detail);
  return (
    <section className={`ccui-tool-card status-${block.status}`} data-tool-block={block.id}>
      <button
        aria-expanded={hasDetail ? open : undefined}
        className="ccui-tool-head"
        disabled={!hasDetail}
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span aria-hidden="true" className="ccui-tool-status" />
        <span className="ccui-tool-main">
          <strong>{block.name}</strong>
          {block.summary ? <span>{block.summary}</span> : null}
        </span>
        <span className="ccui-tool-meta">
          {TOOL_STATUS_LABEL[block.status]}
          {hasDetail ? <i aria-hidden="true">{open ? '收起' : '详情'}</i> : null}
        </span>
      </button>
      {open && hasDetail ? (
        <div className="ccui-tool-body">
          {block.input ? <div><span className="ccui-tool-label">调用</span><pre>{block.input}</pre></div> : null}
          {detail ?? (block.output ? <div><span className="ccui-tool-label">证据</span><pre>{block.output}</pre></div> : null)}
        </div>
      ) : null}
      {action ? <footer className="ccui-tool-action">{action}</footer> : null}
    </section>
  );
}
