import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/primitives';
import { useControlTransport } from '@/app/control-transport';
import { parseRoomEventSnapshot } from '@/contracts/room-reducer';
import { agentCommandReceiptFailure, publicAgentErrorText } from '@/features/agent/public-error';
import type { RoomSummary } from '@/features/rooms/room-types';
import { roomProjection, useRoomLiveStore } from '@/features/rooms/state/live-store';
import { labConnectionKey, requestLabControl } from './control-request';

type DispatchState = 'sending' | 'checking' | 'unknown' | 'failed' | 'pending' | 'conflict';
export type CandidateDispatch = {
  experimentId: string;
  room: RoomSummary;
  body: { message: string; clientMessageId: string };
  originalClientMessageId: string;
  state: DispatchState;
  error: string;
};
type Dispatches = Record<string, CandidateDispatch>;
const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

function restore(storageKey: string): Dispatches {
  try {
    return Object.fromEntries(Object.entries(object(JSON.parse(sessionStorage.getItem(storageKey) ?? '{}'))).flatMap(([id, value]) => {
      const item = object(value), body = object(item.body), room = object(item.room);
      if (item.experimentId !== id || room.ownerAppId !== 'extension:agent-lab' || typeof room.id !== 'string'
        || typeof body.message !== 'string' || typeof body.clientMessageId !== 'string'
        || typeof item.originalClientMessageId !== 'string' || !['sending', 'checking', 'unknown', 'failed', 'pending', 'conflict'].includes(String(item.state))) return [];
      return [[id, { ...item, state: item.state === 'sending' || item.state === 'checking' ? 'unknown' : item.state } as CandidateDispatch]];
    }));
  } catch { return {}; }
}

/** Own only the first dispatch envelope. Room owns admission, turns and recovery. */
export function useCandidateRoomDispatch() {
  const transport = useControlTransport();
  const client = useQueryClient();
  const connection = labConnectionKey(transport);
  const queryKey = ['agent-lab-candidate-dispatch', connection] as const;
  const storageKey = `paw.lab.candidate-dispatch.v1:${connection}`;
  const query = useQuery<Dispatches>({ queryKey, queryFn: skipToken, initialData: () => restore(storageKey), gcTime: Infinity });
  const get = (experimentId: string) => client.getQueryData<Dispatches>(queryKey)?.[experimentId];
  const save = (experimentId: string, pending?: CandidateDispatch) => {
    const next = { ...client.getQueryData<Dispatches>(queryKey) };
    if (pending) next[experimentId] = pending; else delete next[experimentId];
    client.setQueryData(queryKey, next);
    try { if (Object.keys(next).length) sessionStorage.setItem(storageKey, JSON.stringify(next)); else sessionStorage.removeItem(storageKey); } catch { /* In-memory recovery remains available. */ }
  };
  const fail = (pending: CandidateDispatch, error: unknown) => {
    const receipt = agentCommandReceiptFailure(error);
    const state = receipt?.clientMessageId === pending.body.clientMessageId
      ? receipt.state === 'failed' ? 'failed' : receipt.state === 'pending' ? 'pending' : receipt.state === 'conflict' ? 'conflict' : 'unknown'
      : 'unknown';
    save(pending.experimentId, { ...pending, state, error: publicAgentErrorText(error, '派发回执尚未确认，请核对原 Room。') });
  };
  const send = async (pending: CandidateDispatch) => {
    save(pending.experimentId, { ...pending, state: 'sending', error: '' });
    try {
      let response = object(await requestLabControl(transport, { pathId: 'agent.room.message', params: { roomId: pending.room.id }, body: pending.body }));
      const gate = object(response.startConfirmation);
      if (gate.status === 'pending' && typeof gate.gateId === 'string') {
        // Same compatibility path as the shared Room composer; dispatch is authorization.
        response = object(await requestLabControl(transport, { pathId: 'agent.room.startGate.confirm', params: { roomId: pending.room.id }, body: { gateId: gate.gateId, decision: 'confirm' } }));
      }
      if (response.ok !== true || response.accepted === false
        || typeof response.roomId === 'string' && response.roomId !== pending.room.id
        || typeof response.clientMessageId === 'string' && response.clientMessageId !== pending.body.clientMessageId) throw new Error('派发回执与原 Room 任务不匹配，请核对执行记录。');
      useRoomLiveStore.getState().acceptMessage(pending.room.id, response);
      save(pending.experimentId);
    } catch (error) { fail(pending, error); }
  };
  const reconcile = async (pending: CandidateDispatch): Promise<'accepted' | 'unconfirmed' | 'unavailable'> => {
    save(pending.experimentId, { ...pending, state: 'checking', error: '' });
    try {
      const snapshot = parseRoomEventSnapshot(await requestLabControl(transport, { pathId: 'agent.room.snapshot', params: { roomId: pending.room.id } }));
      if (snapshot.room.id !== pending.room.id) throw new Error('Room 状态身份不匹配。');
      useRoomLiveStore.getState().replaySnapshot(pending.room.id, snapshot);
      const accepted = Object.values(roomProjection(pending.room.id).messagesById).some((message) => message.projectionKind !== 'optimistic' && message.role === 'user'
        && (message.clientMessageId === pending.body.clientMessageId || message.clientMessageId === pending.originalClientMessageId));
      if (accepted) { save(pending.experimentId); return 'accepted'; }
      save(pending.experimentId, pending);
      return 'unconfirmed';
    } catch (error) {
      save(pending.experimentId, { ...pending, error: publicAgentErrorText(error, '暂时无法读取 Room，已保留原派发。') });
      return 'unavailable';
    }
  };
  return {
    pending: query.data ?? {}, get,
    async begin(experimentId: string, room: RoomSummary, message: string) {
      if (get(experimentId)) return;
      const clientMessageId = `lab-candidate:${crypto.randomUUID()}`;
      await send({ experimentId, room, body: { message, clientMessageId }, originalClientMessageId: clientMessageId, state: 'sending', error: '' });
    },
    async refresh(experimentId: string) {
      const pending = get(experimentId);
      if (pending && pending.state !== 'sending' && pending.state !== 'checking') await reconcile(pending);
    },
    async retry(experimentId: string) {
      const pending = get(experimentId);
      if (!pending || pending.state !== 'unknown' && pending.state !== 'failed') return;
      if (await reconcile(pending) !== 'unconfirmed') return;
      // A failed command cannot be replayed. This explicit action starts a new
      // attempt in the existing Room, as its shared composer does; the original
      // identity stays attached locally. Unknown admission reuses the exact body.
      await send(pending.state === 'failed' ? { ...pending, body: { ...pending.body, clientMessageId: `lab-candidate:${crypto.randomUUID()}` } } : pending);
    },
  };
}

export function CandidateDispatchRecovery({ pending, onRefresh, onRetry }: {
  pending: CandidateDispatch; onRefresh: () => void; onRetry: () => void;
}) {
  const busy = pending.state === 'sending' || pending.state === 'checking';
  return <section className="lab-workspace__notice" aria-label="原 Room 派发恢复">
    <strong>{busy ? '正在核对原 Room 的任务派发…' : pending.state === 'failed' ? 'Room 已建立，首条任务未被接收' : 'Room 已建立，首条任务派发尚未确认'}</strong>
    <p>已保留原 Room 和原任务；在这次派发确认前，新的实验设置不会再创建一个 Room。</p>
    {pending.error ? <p role="alert">{pending.error}</p> : null}
    {pending.state === 'pending' || pending.state === 'conflict' ? <p>请刷新原 Room 检查已发生的执行；后续继续或重试使用下方 Room 的恢复入口。</p> : null}
    <div className="lab-workspace__form-actions"><Button disabled={busy} onClick={onRefresh} size="small" variant="secondary">刷新 Room 状态</Button>{pending.state === 'unknown' || pending.state === 'failed' ? <Button onClick={onRetry} size="small" variant="primary">{pending.state === 'failed' ? '在原 Room 重试派发' : '核对并重试原派发'}</Button> : null}</div>
    <details><summary>原任务与派发身份</summary><p>{pending.room.title} · {pending.room.id}</p><p>原派发：{pending.originalClientMessageId}</p>{pending.body.clientMessageId !== pending.originalClientMessageId ? <p>当前尝试：{pending.body.clientMessageId}</p> : null}<p className="golden-preserve-text">{pending.body.message}</p></details>
  </section>;
}
