import { useMutation } from '@tanstack/react-query';
import { Play, Square } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/primitives';
import type { JsonValue } from '@/platform/transport';
import type { MutationAvailability } from '@/features/overview/management-mutation';
import {
  InlineNotice,
  StatusBadge,
  asRecord,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import { knowledgeStatusLabel } from './KnowledgeVisualization';

type KnowledgeSessionReceipt = {
  sessionId: string;
  status: string;
};

export function KnowledgeSessionWorkflow({
  availability,
  description,
  draft,
  onCancel,
  onSessionStarted,
  onStart,
  title,
}: {
  availability: MutationAvailability;
  description: string;
  draft: Record<string, JsonValue>;
  draftKey: string;
  onCancel: (sessionId: string) => Promise<unknown>;
  onSessionStarted: (sessionId: string) => void;
  onStart: (boundDraft: Record<string, JsonValue>) => Promise<unknown>;
  previewLines: readonly string[];
  risk: 'R1' | 'R2';
  title: string;
}) {
  const [stage, setStage] = useState<'idle' | 'receipt' | 'cancelled'>('idle');
  const [receipt, setReceipt] = useState<KnowledgeSessionReceipt | null>(null);
  const [cancelReceipt, setCancelReceipt] = useState<KnowledgeSessionReceipt | null>(null);

  const startMutation = useMutation({
    mutationKey: ['knowledge', 'session-workflow', 'start'],
    mutationFn: async (payload: Record<string, JsonValue>) => parseKnowledgeSession(await onStart(payload)),
    onSuccess: (nextReceipt) => {
      setReceipt(nextReceipt);
      setStage('receipt');
      onSessionStarted(nextReceipt.sessionId);
    },
  });
  const cancelMutation = useMutation({
    mutationKey: ['knowledge', 'session-workflow', 'cancel'],
    mutationFn: async (sessionId: string) => parseKnowledgeSession(await onCancel(sessionId), sessionId),
    onSuccess: (nextReceipt) => {
      setCancelReceipt(nextReceipt);
      setStage('cancelled');
    },
  });

  const actionable = availability.state === 'available';

  return (
    <div className="mgmt-workflow" data-availability={availability.state} data-confirmation="direct" data-stage={stage}>
      <div className="mgmt-workflow__heading">
        <div>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        {stage === 'idle' && (availability.state === 'available' || availability.state === 'checking') ? (
          <Button
            disabled={!actionable}
            leadingIcon={<Play size={15} />}
            loading={availability.state === 'checking' || startMutation.isPending}
            onClick={() => startMutation.mutate({ ...draft })}
            size="small"
            variant="primary"
          >
            {title}
          </Button>
        ) : null}
      </div>

      {availability.state !== 'available' && availability.state !== 'checking' && availability.reason ? (
        availability.state === 'unsupported' ? (
          <InlineNotice title="当前不可用" tone="warning">{availability.reason}</InlineNotice>
        ) : <p className="mgmt-workflow__hint">{availability.reason}</p>
      ) : null}

      {startMutation.error ? (
        <InlineNotice title="启动失败" tone="danger">{publicErrorText(startMutation.error, '知识服务暂时无法完成这项请求，请检查连接后重试。')}</InlineNotice>
      ) : null}

      {stage === 'receipt' && receipt ? (
        <div className="mgmt-workflow__receipt">
          <div>
            <StatusBadge label="任务已接受" tone="success" />
            <strong>知识任务正在处理</strong>
            <span>{knowledgeStatusLabel(receipt.status)}</span>
          </div>
          <Button leadingIcon={<Square size={13} />} loading={cancelMutation.isPending} onClick={() => cancelMutation.mutate(receipt.sessionId)} size="small">
            停止整理
          </Button>
        </div>
      ) : null}

      {cancelMutation.error ? (
        <InlineNotice title="取消失败" tone="danger">{publicErrorText(cancelMutation.error, '暂时无法取消这项知识任务，请稍后重试。')}</InlineNotice>
      ) : null}

      {stage === 'cancelled' && cancelReceipt ? (
        <div className="mgmt-workflow__receipt">
          <div>
            <StatusBadge label="已取消" tone="info" />
            <strong>本次知识任务已停止</strong>
            <span>{knowledgeStatusLabel(cancelReceipt.status)}</span>
          </div>
          <Button onClick={() => reset()} size="small" variant="quiet">完成</Button>
        </div>
      ) : null}
    </div>
  );

  function reset() {
    setStage('idle');
    setReceipt(null);
    setCancelReceipt(null);
    startMutation.reset();
    cancelMutation.reset();
  }
}

function parseKnowledgeSession(value: unknown, expectedSessionId = ''): KnowledgeSessionReceipt {
  const payload = asRecord(value);
  const sessionId = stringValue(payload.sessionId, stringValue(payload.id));
  const status = stringValue(payload.status);
  if (payload.ok !== true) throw new Error(knowledgeRequestError(payload));
  if (!sessionId || (expectedSessionId && sessionId !== expectedSessionId) || !status) {
    throw new Error('知识任务状态暂时无法确认。');
  }
  return { sessionId, status };
}

function knowledgeRequestError(payload: Record<string, unknown>): string {
  const status = stringValue(payload.status);
  const error = stringValue(payload.error, stringValue(payload.message));
  if (status === 'blocked') return '当前知识服务尚未就绪，任务没有启动。';
  if (/sensitive|secure/i.test(error)) return '请求中可能包含敏感内容，任务没有启动。';
  if (/sessionId|provider|route|credential|schema|token|hash/i.test(error)) {
    return '知识服务暂时无法完成这项请求，请检查连接后重试。';
  }
  return error || '知识任务请求失败。';
}
