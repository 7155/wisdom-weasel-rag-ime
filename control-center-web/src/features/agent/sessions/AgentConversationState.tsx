import { AlertCircle, MessageSquarePlus } from 'lucide-react';
import { Button, EmptyState } from '@/components/primitives';

function AgentComposerPending() {
  return (
    <div aria-label="正在准备对话" className="agent-composer-wrap" role="status">
      <div className="agent-composer agent-composer--pending">
        <span>正在准备对话</span>
      </div>
    </div>
  );
}

export function AgentConversationState({
  loading,
  error,
  onCreate,
  onOpenRail,
}: {
  loading: boolean;
  error: string;
  onCreate: () => void;
  onOpenRail: () => void;
}) {
  if (loading) return <AgentComposerPending />;
  if (error) {
    return (
      <div className="agent-conversation-state">
        <EmptyState
          icon={AlertCircle}
          title="无法读取对话"
          description="对话列表暂时不可用。打开列表可查看具体错误并重新读取。"
          action={<Button size="small" onClick={onOpenRail}>打开对话列表</Button>}
        />
      </div>
    );
  }
  return (
    <div className="agent-conversation-state">
      <EmptyState
        icon={MessageSquarePlus}
        title="还没有对话"
        description="新建一段对话后，Agent 会在这里显示消息与工作状态。"
        action={<Button size="small" leadingIcon={<MessageSquarePlus size={15} />} onClick={onCreate}>新建对话</Button>}
      />
    </div>
  );
}
