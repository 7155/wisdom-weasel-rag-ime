import React from "react";

export function JumpToBottom({ visible, onClick }: { visible: boolean; onClick(): void }) {
  if (!visible) return null;
  return (
    <button type="button" className="ccui-jump-bottom" onClick={onClick} aria-label="Jump to latest message">
      ↓ <span>Latest</span>
    </button>
  );
}
