import { Check, FolderOpen, ShieldCheck } from 'lucide-react';
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
import { roomParticipantPlanetName } from './room-participant-identity';

interface RoomMemberIdentity {
  sessionId: string;
  ordinal: number;
}

type RoomExecutionMode = 'read_only' | 'per_action' | 'workspace_managed' | 'full_trust';

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

export function RoomMemberBoundaryDialog({
  executionMode,
  participant,
  workspaceRoots,
  onClose,
}: {
  executionMode?: RoomExecutionMode;
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

  const baseToolIds = new Set(PI_SESSION_BASE_TOOLS.map((tool) => tool.id));
  const enabledTools = tools.filter((tool) => tool.enabled && !baseToolIds.has(tool.id));
  const availableToolCount = PI_SESSION_BASE_TOOLS.length + enabledTools.length;
  return (
    <Dialog open={Boolean(participant)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="room-policy-dialog">
        <DialogHeader>
          <DialogTitle>{roomParticipantPlanetName(participant)} 能做什么</DialogTitle>
          <DialogDescription>
            这里显示真正生效的工作权限、目录和工具。分工只是协作提示，不会让伙伴绕过你的授权。
          </DialogDescription>
        </DialogHeader>
        {error ? <p className="room-dialog-error" role="alert">{error}</p> : null}
        {participant ? (
          <div className="room-policy-form">
            <div className="room-policy-boundary">
              <ShieldCheck size={18} />
              <span>
                <strong>{executionModeLabel(executionMode)}</strong>
                <small>{loading ? '4 项 Session 基础工具已就绪，正在确认扩展能力；' : `${availableToolCount} 项工具可用，其中 4 项为 Session 基础工具；`}{executionMode === 'full_trust' ? '独立审批助手（Luna Max）依据整个协作空间的结构化审批记录判定待审批操作；' : ''}停止任务、目录边界、删库、灾难性破坏和敏感数据外传禁区始终有效。</small>
              </span>
            </div>
            <fieldset>
              <legend>可以工作的目录 <small>{workspaceRoots.length} 项</small></legend>
              {workspaceRoots.length ? (
                <div className="room-policy-roots">
                  {workspaceRoots.map((path) => (
                    <span key={path}><FolderOpen size={14} /><small>{path}</small></span>
                  ))}
                </div>
              ) : <p className="room-policy-empty">这个协作空间不会访问项目目录。</p>}
            </fieldset>
            <Disclosure
              className="room-policy-tools-disclosure"
              summary={<>看看可以使用哪些工具 <small>{loading ? '4 项基础工具，扩展能力确认中' : `${availableToolCount} 项`}</small></>}
            >
              <p className="room-policy-tools-heading"><strong>Session 基础工具</strong><small>由 Pi 原生暴露，真实执行仍受当前目录与工作权限约束。</small></p>
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

function executionModeLabel(executionMode: RoomExecutionMode | undefined): string {
  return {
    read_only: '只读',
    per_action: '每次确认',
    workspace_managed: '工作区托管',
    full_trust: '全自动',
  }[executionMode ?? 'per_action'];
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
