import { Blocks, PackageMinus, PackageOpen, RotateCcw } from 'lucide-react';
import { Disclosure } from '@/components/primitives';

import type {
  RoomSurfaceModuleDefinition,
  RoomSurfaceModuleId,
} from './room-surface-modules';

export function RoomModulePanel({
  definitions,
  isMounted,
  onReset,
  onSetMounted,
}: {
  definitions: readonly RoomSurfaceModuleDefinition[];
  isMounted: (id: RoomSurfaceModuleId) => boolean;
  onReset: () => void;
  onSetMounted: (id: RoomSurfaceModuleId, mounted: boolean) => void;
}) {
  const mountedCount = definitions.filter((module) => isMounted(module.id)).length;
  return <Disclosure
    className="room-module-panel"
    contentClassName="room-module-panel__surface"
    summary={(
      <span aria-label="管理 Room 界面模块" className="room-module-panel__summary">
        <Blocks aria-hidden="true" size={15} />
        <span>模块</span>
        <small>{mountedCount}/{definitions.length}</small>
      </span>
    )}
  >
    <header>
      <span><strong>Room 界面模块</strong><small>组合投影，而不是复制 Runtime</small></span>
      <button onClick={onReset} type="button"><RotateCcw size={13} />恢复默认</button>
    </header>
    <p>装载或移出只改变当前设备上的 Room 阅读界面，不删除历史，不改变 Pi、工具权限或正在运行的任务。</p>
    <ul>
      {definitions.map((module) => {
        const mounted = isMounted(module.id);
        return <li data-mounted={mounted} key={module.id}>
          <span>
            <small>{slotLabel(module.slot)}</small>
            <strong>{module.name}</strong>
            <p>{module.description}</p>
          </span>
          <button
            aria-label={`${mounted ? '移出' : '装载'}${module.name}`}
            onClick={() => onSetMounted(module.id, !mounted)}
            type="button"
          >
            {mounted ? <PackageMinus size={14} /> : <PackageOpen size={14} />}
            {mounted ? '移出' : '装载'}
          </button>
        </li>;
      })}
    </ul>
  </Disclosure>;
}

function slotLabel(slot: RoomSurfaceModuleDefinition['slot']): string {
  return ({ navigation: '导航', execution: '执行', evidence: '证据' })[slot];
}
