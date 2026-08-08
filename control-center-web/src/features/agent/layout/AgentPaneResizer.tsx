import { WorkspacePaneResizer } from '@/components/layout/WorkspacePaneResizer';

type PaneSide = 'rail' | 'status';

const PANE_CONFIG = {
  rail: {
    defaultSize: 224,
    min: 196,
    max: 320,
    storageKey: 'wisdom-weasel.agent.rail-width',
    variable: '--agent-rail-width',
    label: '调整对话列表宽度',
  },
  status: {
    defaultSize: 312,
    min: 280,
    max: 420,
    storageKey: 'wisdom-weasel.agent.status-width',
    variable: '--agent-status-width',
    label: '调整任务中心宽度',
  },
} as const;

export function AgentPaneResizer({ side }: { side: PaneSide }) {
  return <WorkspacePaneResizer
    {...PANE_CONFIG[side]}
    className="agent-pane-resizer"
    side={side}
    workspaceSelector=".agent-feature"
  />;
}
