import { WorkspacePaneResizer } from '@/components/layout/WorkspacePaneResizer';

type PaneSide = 'rail' | 'status';

const PANE_CONFIG = {
  rail: {
    defaultSize: 224,
    min: 196,
    max: 320,
    storageKey: 'wisdom-weasel.rooms.rail-width',
    variable: '--room-rail-width',
    label: '调整协作空间列表宽度',
  },
  status: {
    defaultSize: 312,
    min: 280,
    max: 420,
    storageKey: 'wisdom-weasel.rooms.status-width',
    variable: '--room-status-width',
    label: '调整协作进展面板宽度',
  },
} as const;

export function RoomPaneResizer({ side }: { side: PaneSide }) {
  return <WorkspacePaneResizer
    {...PANE_CONFIG[side]}
    className="room-pane-resizer"
    side={side}
    workspaceSelector=".rooms-feature"
  />;
}
