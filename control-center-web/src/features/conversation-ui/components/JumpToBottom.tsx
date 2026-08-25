import { ArrowDown } from 'lucide-react';

export function JumpToBottom({ visible, onClick }: { visible: boolean; onClick(): void }) {
  if (!visible) return null;
  return (
    <button aria-label="回到最新消息" className="ccui-jump-bottom" onClick={onClick} type="button">
      <ArrowDown aria-hidden="true" size={13} />
      <span>最新</span>
    </button>
  );
}
