import { useState, type ReactNode } from 'react';
import type { ThinkingBlock as ThinkingBlockModel } from '../model/types';

export function ThinkingBlock({ block, detail }: {
  block: ThinkingBlockModel;
  /** Host-rendered body, used when the Runtime detail is richer than text. */
  detail?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const body = detail ?? (block.detail ? <div className="ccui-thinking-detail">{block.detail}</div> : null);
  return (
    <section className={`ccui-thinking${block.status === 'running' ? ' is-running' : ''}`}>
      <button
        aria-expanded={body ? open : undefined}
        className="ccui-thinking-summary"
        disabled={!body}
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span aria-hidden="true" className="ccui-thinking-dot" />
        <span>{block.summary || (block.status === 'running' ? '正在思考' : '已形成思路')}</span>
        {body ? <span className="ccui-caret">{open ? '收起' : '展开'}</span> : null}
      </button>
      {open ? body : null}
    </section>
  );
}
