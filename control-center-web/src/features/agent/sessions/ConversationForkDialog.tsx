import { CornerDownRight, GitBranch, LoaderCircle } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import * as RadioGroup from '@radix-ui/react-radio-group';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/primitives';
import { publicAgentErrorText } from '../public-error';
import type { SessionSummary } from '../types';

interface ForkCandidate {
  entryId: string;
  text: string;
}

interface PathNode extends ConversationNode {
  key: string;
  branchEntryId?: string;
  jumpEntryId?: string;
}

export interface ConversationNode {
  entryId: string;
  role: 'user' | 'assistant';
  text: string;
  createdAtMs: number;
}

export function ConversationForkDialog({
  open,
  sessionId,
  sessionTitle,
  nodes,
  initialEntryId,
  branchAvailable,
  branchBlocked,
  onOpenChange,
  onJump,
  onCreated,
}: {
  open: boolean;
  sessionId: string;
  sessionTitle: string;
  nodes: ConversationNode[];
  initialEntryId?: string;
  branchAvailable: boolean;
  branchBlocked: boolean;
  onOpenChange: (open: boolean) => void;
  onJump: (entryId: string) => void;
  onCreated: (session: SessionSummary, selectedText: string) => void;
}) {
  const transport = useControlTransport();
  const [items, setItems] = useState<ForkCandidate[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open || !sessionId) return;
    const preferred = nodes.some((item) => item.entryId === initialEntryId)
      ? initialEntryId ?? ''
      : nodes.at(-1)?.entryId ?? '';
    setSelectedId(preferred);
    if (!branchAvailable || branchBlocked) {
      setItems([]);
      setLoading(false);
      setError('');
      return;
    }
    let active = true;
    setLoading(true);
    setError('');
    void transport.request<Record<string, unknown>>({
      pathId: 'agent.session.forks.list',
      params: { sessionId },
    }).then((response) => {
      if (!active) return;
      const candidates = forkCandidates(response);
      setItems(candidates);
    }).catch((requestError) => {
      if (!active) return;
      setItems([]);
      setError(publicAgentErrorText(requestError, '历史分支点暂时无法读取。'));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [branchAvailable, branchBlocked, initialEntryId, nodes, open, sessionId, transport]);

  const pathNodes = useMemo(() => mergePathNodes(nodes, items), [items, nodes]);
  const selectedNode = useMemo(() => pathNodes.find((item) => item.key === selectedId), [pathNodes, selectedId]);
  const selectedCandidate = useMemo(
    () => items.find((item) => item.entryId === selectedNode?.branchEntryId),
    [items, selectedNode?.branchEntryId],
  );

  async function createFork(): Promise<void> {
    if (!selectedCandidate || creating || branchBlocked) return;
    setCreating(true);
    setError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.forks.create',
        params: { sessionId },
        body: { entryId: selectedCandidate.entryId, title: `${sessionTitle} · 分支` },
      });
      const session = record(response.session) as unknown as SessionSummary;
      if (!session.id) throw new Error('后端没有返回新分支会话。');
      onCreated(session, text(response.selectedText) || selectedCandidate.text);
      onOpenChange(false);
    } catch (requestError) {
      setError(publicAgentErrorText(requestError, '创建对话分支失败。'));
    } finally {
      setCreating(false);
    }
  }

  function jumpToNode(): void {
    if (!selectedNode?.jumpEntryId) return;
    onJump(selectedNode.jumpEntryId);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !creating && onOpenChange(next)}>
      <DialogContent className="agent-fork-dialog">
        <DialogHeader>
          <DialogTitle><GitBranch size={18} />对话路径</DialogTitle>
          <DialogDescription>所有消息都可回溯定位；用户消息是 Pi 的真实分支锚点，创建后原对话保持不变。</DialogDescription>
        </DialogHeader>
        {pathNodes.length ? (
          <RadioGroup.Root className="agent-fork-dialog__list" aria-label="对话分支点" value={selectedId} onValueChange={setSelectedId}>
            {pathNodes.map((item, index) => {
              const branchable = Boolean(item.branchEntryId);
              return (
              <RadioGroup.Item
                key={item.key}
                value={item.key}
                data-selected={item.key === selectedId}
              >
                <span className="agent-fork-dialog__index">{index + 1}</span>
                <span className="agent-fork-dialog__node-copy">
                  <small>{item.role === 'user' ? '你' : '智鼬'} · {formatNodeTime(item.createdAtMs)}</small>
                  <strong>{item.text}</strong>
                </span>
                <em data-branchable={branchable || undefined}>{branchable ? '可分支' : '可跳转'}</em>
              </RadioGroup.Item>
              );
            })}
          </RadioGroup.Root>
        ) : (
          <div className="agent-fork-dialog__state">当前对话还没有可回溯的消息。</div>
        )}
        {loading ? <p className="agent-fork-dialog__status"><LoaderCircle size={14} />正在核对 Pi 分支锚点</p> : null}
        {branchBlocked ? <p className="agent-fork-dialog__status">当前回合结束后可创建分支，历史节点仍可直接跳转。</p> : null}
        {!branchAvailable ? <p className="agent-fork-dialog__status">当前运行时未提供分支能力，历史节点仍可直接跳转。</p> : null}
        {error ? <p className="agent-fork-dialog__error" role="alert">{error} 历史节点仍可直接跳转。</p> : null}
        <footer>
          <Button variant="quiet" onClick={() => onOpenChange(false)} disabled={creating}>取消</Button>
          <Button variant="quiet" leadingIcon={<CornerDownRight size={15} />} onClick={jumpToNode} disabled={!selectedNode?.jumpEntryId || creating}>跳到节点</Button>
          <Button onClick={() => void createFork()} disabled={!selectedCandidate || loading || creating || branchBlocked}>
            {creating ? <><LoaderCircle size={15} />正在创建</> : <><GitBranch size={15} />创建分支</>}
          </Button>
        </footer>
      </DialogContent>
    </Dialog>
  );
}

function mergePathNodes(nodes: ConversationNode[], candidates: ForkCandidate[]): PathNode[] {
  const remaining = new Map(candidates.map((candidate) => [candidate.entryId, candidate]));
  const path = nodes.map((node): PathNode => {
    const candidate = remaining.get(node.entryId);
    if (candidate) remaining.delete(candidate.entryId);
    return {
      ...node,
      key: node.entryId,
      jumpEntryId: node.entryId,
      branchEntryId: candidate?.entryId,
    };
  });

  // Pi's branch entry id is not guaranteed to equal the projected message id.
  // Match the remaining public user nodes by stable occurrence order, but only
  // when the counts agree. A partial or ambiguous catalog fails closed rather
  // than branching from the wrong repeated message.
  const nodesByText = new Map<string, PathNode[]>();
  for (const node of path) {
    if (node.role !== 'user' || node.branchEntryId) continue;
    const normalized = normalizeText(node.text);
    nodesByText.set(normalized, [...(nodesByText.get(normalized) ?? []), node]);
  }
  const candidatesByText = new Map<string, ForkCandidate[]>();
  for (const candidate of remaining.values()) {
    const normalized = normalizeText(candidate.text);
    candidatesByText.set(normalized, [...(candidatesByText.get(normalized) ?? []), candidate]);
  }
  for (const [normalized, publicNodes] of nodesByText) {
    const matching = candidatesByText.get(normalized) ?? [];
    if (matching.length !== publicNodes.length) continue;
    publicNodes.forEach((node, index) => { node.branchEntryId = matching[index]?.entryId; });
  }
  return path;
}

function normalizeText(value: string): string {
  return value.replace(/\s+/gu, ' ').trim();
}

function formatNodeTime(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '历史消息';
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(value);
}

function forkCandidates(value: unknown): ForkCandidate[] {
  const items = Array.isArray(record(value).items) ? record(value).items as unknown[] : [];
  return items.map((item) => record(item)).filter((item) => (
    typeof item.entryId === 'string' && item.entryId.length > 0
      && typeof item.text === 'string' && item.text.trim().length > 0
      && !item.text.includes('<rag-ime-deep-search-context')
      && !item.text.includes('<rag-ime-user-query>')
  )).map((item) => ({ entryId: text(item.entryId), text: text(item.text).trim() })).slice(0, 500);
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
