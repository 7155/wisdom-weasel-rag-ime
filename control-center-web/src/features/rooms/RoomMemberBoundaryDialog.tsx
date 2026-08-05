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
} from '@/components/primitives';
import {
  projectPublicToolCatalog,
  publicToolName,
} from '@/features/agent/tool-presentation';
import { publicErrorText } from '@/features/overview/management-ui';

interface RoomMemberIdentity {
  displayName: string;
  sessionId: string;
}

type RoomExecutionMode = 'read_only' | 'per_action' | 'workspace_managed' | 'full_trust';

interface RoomToolCatalogItem {
  id: string;
  displayName: string;
  description: string;
  enabled: boolean;
}

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

  const enabledTools = tools.filter((tool) => tool.enabled);
  return (
    <Dialog open={Boolean(participant)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="room-policy-dialog">
        <DialogHeader>
          <DialogTitle>{participant?.displayName ?? '这位伙伴'}能做什么</DialogTitle>
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
                <small>{loading ? '正在确认可用工具；' : `${enabledTools.length} 项工具可用；`}{executionMode === 'full_trust' ? '独立审批助手（Luna Max）依据整个协作空间的结构化审批记录判定待审批操作；' : ''}停止任务、目录边界、删库、灾难性破坏和敏感数据外传禁区始终有效。</small>
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
            <details className="room-policy-tools-disclosure">
              <summary>看看可以使用哪些工具 <small>{loading ? '确认中' : `${enabledTools.length} 项`}</small></summary>
              {loading ? <p className="room-policy-loading" role="status">正在确认可用工具…</p> : (
                <div className="room-policy-tools">
                  {enabledTools.map((tool) => (
                    <div key={tool.id}>
                      <Check size={14} />
                      <span><strong>{publicToolName(tool.id, tool.displayName)}</strong><small>{tool.description}</small></span>
                    </div>
                  ))}
                </div>
              )}
            </details>
          </div>
        ) : null}
        <DialogFooter><Button variant="primary" onClick={onClose}>知道了</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function roomToolCatalogItems(value: unknown): RoomToolCatalogItem[] {
  const source = record(value);
  const items = (Array.isArray(source.items) ? source.items : []).flatMap((value) => {
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
  return projectPublicToolCatalog(items);
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
