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
import { publicErrorText } from '@/features/overview/management-ui';

interface RoomMemberIdentity {
  displayName: string;
  sessionId: string;
}

interface RoomMemberSessionBoundary {
  id: string;
  workspaceRoots: string[];
}

interface RoomToolCatalogItem {
  id: string;
  displayName: string;
  description: string;
  enabled: boolean;
}

export function RoomMemberBoundaryDialog({
  participant,
  onClose,
}: {
  participant?: RoomMemberIdentity;
  onClose: () => void;
}) {
  const transport = useControlTransport();
  const [session, setSession] = useState<RoomMemberSessionBoundary>();
  const [tools, setTools] = useState<RoomToolCatalogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!participant) {
      setSession(undefined);
      setTools([]);
      setLoading(false);
      setError('');
      return;
    }
    const controller = new AbortController();
    let active = true;
    setSession(undefined);
    setTools([]);
    setError('');
    setLoading(true);
    void Promise.all([
      transport.request({
        pathId: 'agent.sessions.list',
        query: { includeArchived: true, includeInternal: true, limit: 500 },
        signal: controller.signal,
      }),
      transport.request({
        pathId: 'agent.tools.list',
        query: { sessionId: participant.sessionId },
        signal: controller.signal,
      }),
    ]).then(([sessionResponse, toolResponse]) => {
      if (!active) return;
      const nextSession = roomMemberSessionItems(sessionResponse)
        .find((item) => item.id === participant.sessionId);
      if (!nextSession) {
        throw new Error('没有找到这个参与者的 Agent Session。');
      }
      setSession(nextSession);
      setTools(roomToolCatalogItems(toolResponse));
    }).catch((requestError: unknown) => {
      if (!active || controller.signal.aborted) return;
      setError(publicErrorText(
        requestError,
        '参与者运行边界暂时无法读取，请稍后重试。',
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
          <DialogTitle>{participant?.displayName ?? '参与者'} · 运行边界</DialogTitle>
          <DialogDescription>
            Room 身份只决定责任与交接，不裁掉工作能力。成员使用完整 Agent 工具面，写入、Shell 与外部动作仍按原生审批执行。
          </DialogDescription>
        </DialogHeader>
        {error ? <p className="room-dialog-error" role="alert">{error}</p> : null}
        {loading ? (
          <p className="room-policy-loading" role="status">正在读取 Agent 权限…</p>
        ) : session ? (
          <div className="room-policy-form">
            <div className="room-policy-boundary">
              <ShieldCheck size={18} />
              <span>
                <strong>完整工作权限</strong>
                <small>身份不会把执行者降成只读；工具调用仍受工作区、审批、取消与迟到写入栅栏约束。</small>
              </span>
            </div>
            <fieldset>
              <legend>项目范围 <small>{session.workspaceRoots.length} 项</small></legend>
              {session.workspaceRoots.length ? (
                <div className="room-policy-roots">
                  {session.workspaceRoots.map((path) => (
                    <span key={path}><FolderOpen size={14} /><small>{path}</small></span>
                  ))}
                </div>
              ) : <p className="room-policy-empty">这个 Room 不绑定项目目录。</p>}
            </fieldset>
            <details className="room-policy-tools-disclosure">
              <summary>查看当前工具目录 <small>{enabledTools.length} 项</small></summary>
              <div className="room-policy-tools">
                {enabledTools.map((tool) => (
                  <div key={tool.id}>
                    <Check size={14} />
                    <span><strong>{tool.displayName}</strong><small>{tool.description}</small></span>
                  </div>
                ))}
              </div>
            </details>
          </div>
        ) : null}
        <DialogFooter><Button variant="primary" onClick={onClose}>完成</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function roomMemberSessionItems(value: unknown): RoomMemberSessionBoundary[] {
  const source = record(value);
  const items = Array.isArray(source.items)
    ? source.items
    : Array.isArray(source.sessions) ? source.sessions : [];
  return items.flatMap((value) => {
    const item = record(value);
    return typeof item.id === 'string'
      ? [{
          id: item.id,
          workspaceRoots: Array.isArray(item.workspaceRoots)
            ? item.workspaceRoots.map(String)
            : [],
        }]
      : [];
  });
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
