import React, { useState } from "react";
import type { ToolCallBlock } from "../model/types";

const STATUS_LABEL: Record<ToolCallBlock["status"], string> = {
  pending: "Queued",
  running: "Running",
  success: "Done",
  error: "Failed",
  cancelled: "Cancelled",
};

export function ToolCard({ block }: { block: ToolCallBlock }) {
  const [open, setOpen] = useState(block.status === "error");
  const hasDetail = Boolean(block.input || block.output);
  return (
    <section className={`ccui-tool-card status-${block.status}`}>
      <button type="button" className="ccui-tool-head" onClick={() => hasDetail && setOpen(value => !value)} aria-expanded={open}>
        <span className="ccui-tool-status" aria-hidden="true" />
        <span className="ccui-tool-main">
          <strong>{block.name}</strong>
          {block.summary ? <span>{block.summary}</span> : null}
        </span>
        <span className="ccui-tool-meta">{STATUS_LABEL[block.status]}{hasDetail ? ` ${open ? "⌃" : "⌄"}` : ""}</span>
      </button>
      {open && hasDetail ? (
        <div className="ccui-tool-body">
          {block.input ? <div><span className="ccui-tool-label">Input</span><pre>{block.input}</pre></div> : null}
          {block.output ? <div><span className="ccui-tool-label">Output</span><pre>{block.output}</pre></div> : null}
        </div>
      ) : null}
    </section>
  );
}
