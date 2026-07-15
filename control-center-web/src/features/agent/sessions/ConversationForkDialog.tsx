import { GitBranch, LoaderCircle } from 'lucide-react';
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

export function ConversationForkDialog({
  open,
  sessionId,
  sessionTitle,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  sessionId: string;
  sessionTitle: string;
  onOpenChange: (open: boolean) => void;
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
    let active = true;
    setLoading(true);
    setError('');
    setSelectedId('');
    void transport.request<Record<string, unknown>>({
      pathId: 'agent.session.forks.list',
      params: { sessionId },
    }).then((response) => {
      if (!active) return;
      const candidates = forkCandidates(response);
      setItems(candidates);
      setSelectedId(candidates.at(-1)?.entryId ?? '');
    }).catch((requestError) => {
      if (!active) return;
      setItems([]);
      setError(publicAgentErrorText(requestError, '历史分支点暂时无法读取。'));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [open, sessionId, transport]);

  const selected = useMemo(() => items.find((item) => item.entryId === selectedId), [items, selectedId]);

  async function createFork(): Promise<void> {
    if (!selected || creating) return;
    setCreating(true);
    setError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.forks.create',
        params: { sessionId },
        body: { entryId: selected.entryId, title: `${sessionTitle} · 分支` },
      });
      const session = record(response.session) as unknown as SessionSummary;
      if (!session.id) throw new Error('后端没有返回新分支会话。');
      onCreated(session, text(response.selectedText) || selected.text);
      onOpenChange(false);
    } catch (requestError) {
      setError(publicAgentErrorText(requestError, '创建对话分支失败。'));
    } finally {
      setCreating(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !creating && onOpenChange(next)}>
      <DialogContent className="agent-fork-dialog">
        <DialogHeader>
          <DialogTitle><GitBranch size={18} />从历史消息创建分支</DialogTitle>
          <DialogDescription>原对话保持不变；新分支会回到所选用户消息之前，并把原消息放回输入框供你修改。</DialogDescription>
        </DialogHeader>
        {loading ? (
          <div className="agent-fork-dialog__state"><LoaderCircle size={18} />正在读取可分支的用户消息</div>
        ) : items.length ? (
          <RadioGroup.Root className="agent-fork-dialog__list" aria-label="对话分支点" value={selectedId} onValueChange={setSelectedId}>
            {[...items].reverse().map((item, index) => (
              <RadioGroup.Item
                key={item.entryId}
                value={item.entryId}
                data-selected={item.entryId === selectedId}
              >
                <span>{items.length - index}</span>
                <strong>{item.text}</strong>
              </RadioGroup.Item>
            ))}
          </RadioGroup.Root>
        ) : !error ? (
          <div className="agent-fork-dialog__state">当前对话还没有可用的历史用户消息。</div>
        ) : null}
        {error ? <p className="agent-fork-dialog__error" role="alert">{error}</p> : null}
        <footer>
          <Button variant="quiet" onClick={() => onOpenChange(false)} disabled={creating}>取消</Button>
          <Button onClick={() => void createFork()} disabled={!selected || loading || creating}>
            {creating ? <><LoaderCircle size={15} />正在创建</> : <><GitBranch size={15} />创建分支</>}
          </Button>
        </footer>
      </DialogContent>
    </Dialog>
  );
}

function forkCandidates(value: unknown): ForkCandidate[] {
  const items = Array.isArray(record(value).items) ? record(value).items as unknown[] : [];
  return items.map((item) => record(item)).filter((item) => (
    typeof item.entryId === 'string' && item.entryId.length > 0
      && typeof item.text === 'string' && item.text.trim().length > 0
  )).map((item) => ({ entryId: text(item.entryId), text: text(item.text).trim() })).slice(0, 500);
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
