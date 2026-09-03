import { Check, FolderOpen } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Disclosure,
} from '@/components/primitives';
import { publicToolName } from '@/features/agent/tool-presentation';
import { publicErrorText } from '@/features/overview/management-ui';
import { RoomPermissionPolicyEditor } from './room-presentation';
import { parseRoomPermissionPolicy, type RoomKind } from './room-types';
import { roomParticipantPlanetName } from './room-participant-identity';

interface RoomMemberIdentity {
  sessionId: string;
  ordinal: number;
}


interface RoomToolCatalogItem {
  id: string;
  displayName: string;
  description: string;
  enabled: boolean;
}

const PI_SESSION_BASE_TOOLS: readonly RoomToolCatalogItem[] = [
  {
    id: 'read',
    displayName: '读取文件',
    description: '读取当前授权工作区内的文件。',
    enabled: true,
  },
  {
    id: 'edit',
    displayName: '编辑文件',
    description: '在当前工作权限允许时精确修改已有文件。',
    enabled: true,
  },
  {
    id: 'write',
    displayName: '写入文件',
    description: '在当前工作权限允许时新建或重写文件。',
    enabled: true,
  },
  {
    id: 'bash',
    displayName: '运行命令',
    description: '在当前授权工作区内运行命令。',
    enabled: true,
  },
];

const PI_SESSION_BASE_TOOL_IDS: Record<string, true> = {
  read: true,
  edit: true,
  write: true,
  bash: true,
};

export function RoomMemberBoundaryDialog({
  permissionPolicy,
  roomKind,
  participant,
  workspaceRoots,
  onClose,
}: {
  permissionPolicy?: unknown;
  roomKind?: RoomKind;
  participant?: RoomMemberIdentity;
  workspaceRoots: string[];
  onClose: () => void;
}) {
  const transport = useControlTransport();
  const [tools, setTools] = useState<RoomToolCatalogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!participant) {
      setTools([]);
      setLoading(false);
      setError('');
      return;
    }
    const controller = new AbortController();
    let active = true;
    setTools([]);
    setError('');
    setLoading(true);
    void transport.request({
      pathId: 'agent.tools.list',
      query: { sessionId: participant.sessionId },
      signal: controller.signal,
    }).then((toolResponse) => {
      if (!active) return;
      setTools(roomToolCatalogItems(toolResponse));
    }).catch((requestError: unknown) => {
      if (!active || controller.signal.aborted) return;
      setError(publicErrorText(
        requestError,
        '暂时无法确认这位伙伴可用的工具，请稍后重试。',
      ));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [participant, transport]);

  const enabledTools = tools.filter((tool) => (
    tool.enabled && PI_SESSION_BASE_TOOL_IDS[tool.id] !== true
  ));
  const availableToolCount = PI_SESSION_BASE_TOOLS.length + enabledTools.length;
  const parsedPermissionPolicy = parseRoomPermissionPolicy(permissionPolicy, roomKind);
  const effectiveRoomKind = roomKind ?? 'collaboration';
  return (
    <Dialog open={Boolean(participant)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="room-policy-dialog">
        <DialogHeader>
          <DialogTitle>{roomParticipantPlanetName(participant)} 能做什么</DialogTitle>
          <DialogDescription>
            这里按服务端策略分别显示行星 / Partner 与卫星 / Tool Agent 的实际生效权限。
            分工只是协作提示，不会扩大任何一层授权。
          </DialogDescription>
        </DialogHeader>
        {error ? <p className="room-dialog-error" role="alert">{error}</p> : null}
        {participant ? (
          <div className="room-policy-form">
            <RoomPermissionPolicyEditor
              policy={parsedPermissionPolicy}
              roomKind={effectiveRoomKind}
            />
            <fieldset>
              <legend>起始项目上下文 <small>{workspaceRoots.length} 项</small></legend>
              {workspaceRoots.length ? (
                <div className="room-policy-roots">
                  {workspaceRoots.map((path) => (
                    <span key={path}><FolderOpen size={14} /><small>{path}</small></span>
                  ))}
                </div>
              ) : <p className="room-policy-empty">没有预选项目；具体可达范围以上方分层策略为准。</p>}
            </fieldset>
            <Disclosure
              className="room-policy-tools-disclosure"
              summary={<>看看 Session 暴露了哪些工具 <small>{loading ? '4 项基础工具，扩展能力确认中' : `${availableToolCount} 项`}</small></>}
            >
              <p className="room-policy-tools-heading"><strong>Session 基础工具</strong><small>工具是否可执行及是否需要批准，以上方 Partner 与 Tool Agent 生效层为准。</small></p>
              <div className="room-policy-tools">
                {PI_SESSION_BASE_TOOLS.map((tool) => (
                  <div key={tool.id}>
                    <Check size={14} />
                    <span><strong>{publicToolName(tool.id, tool.displayName)}</strong><small>{tool.description}</small></span>
                  </div>
                ))}
              </div>
              {loading ? <p className="room-policy-loading" role="status">正在确认扩展能力…</p> : enabledTools.length ? <>
                <p className="room-policy-tools-heading"><strong>扩展能力</strong><small>按当前 Session 的能力设置加载。</small></p>
                <div className="room-policy-tools">
                  {enabledTools.map((tool) => (
                    <div key={tool.id}>
                      <Check size={14} />
                      <span><strong>{publicToolName(tool.id, tool.displayName)}</strong><small>{tool.description}</small></span>
                    </div>
                  ))}
                </div>
              </> : <p className="room-policy-empty room-policy-tools-empty">当前没有额外启用的扩展能力。</p>}
            </Disclosure>
          </div>
        ) : null}
        <DialogFooter><Button variant="primary" onClick={onClose}>知道了</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function roomToolCatalogItems(value: unknown): RoomToolCatalogItem[] {
  const source = record(value);
  return (Array.isArray(source.items) ? source.items : []).flatMap((value) => {
    const item = record(value);
    return typeof item.id === 'string' && typeof item.displayName === 'string'
      ? [{
          id: item.id,
          displayName: item.displayName,
          description: String(item.description ?? ''),
          enabled: item.enabled === true,
        }]
      : [];
  });
}


function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
