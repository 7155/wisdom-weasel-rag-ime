import React, { useState } from "react";
import type { ThinkingBlock as ThinkingBlockType } from "../model/types";

export function ThinkingBlock({ block }: { block: ThinkingBlockType }) {
  const [open, setOpen] = useState(false);
  return (
    <section className={`ccui-thinking ${block.status === "running" ? "is-running" : ""}`}>
      <button type="button" className="ccui-thinking-summary" onClick={() => setOpen(value => !value)} aria-expanded={open}>
        <span className="ccui-thinking-dot" aria-hidden="true" />
        <span>{block.summary || (block.status === "running" ? "Thinking…" : "Thought")}</span>
        {block.detail ? <span className="ccui-caret">{open ? "⌃" : "⌄"}</span> : null}
      </button>
      {open && block.detail ? <div className="ccui-thinking-detail">{block.detail}</div> : null}
    </section>
  );
}
