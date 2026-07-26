import { GitBranch, MessagesSquare, Play } from 'lucide-react';

import { Button } from '@/components/primitives';

export function RoomExecutionPhase({
  activeWork,
  ownerName,
  canStart,
  onStart,
}: {
  activeWork?: {
    objective: string;
    state: string;
  };
  ownerName: string;
  canStart: boolean;
  onStart: () => void;
}) {
  if (activeWork) {
    return <div className="room-execution-phase" data-phase="managed">
      <GitBranch size={15} />
      <span>
        <strong>正在完成任务</strong>
        <small>{ownerName} · {activeWork.objective}</small>
      </span>
      <i>{workStateLabel(activeWork.state)}</i>
    </div>;
  }
  return <div className="room-execution-phase" data-phase="alignment">
    <MessagesSquare size={15} />
    <span>
      <strong>先聊清楚再开工</strong>
      <small>确认目标、交付物、验收和禁区后，再请伙伴持续推进。</small>
    </span>
    <Button
      size="small"
      variant="quiet"
      leadingIcon={<Play size={14} />}
      disabled={!canStart}
      onClick={onStart}
    >
      确认任务
    </Button>
  </div>;
}

function workStateLabel(state: string): string {
  return {
    queued: '待执行',
    active: '进行中',
    review: '待验收',
    blocked: '已阻塞',
  }[state] ?? '执行中';
}
