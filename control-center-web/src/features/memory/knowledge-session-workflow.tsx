import { useMutation } from '@tanstack/react-query';
import { Check, CircleDashed, ShieldCheck, Square } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
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
  draftKey,
  onCancel,
  onSessionStarted,
  onStart,
  previewLines,
  risk,
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
  const [stage, setStage] = useState<'idle' | 'preview' | 'approval' | 'receipt' | 'cancelled'>('idle');
  const [approved, setApproved] = useState(false);
  const [boundDraft, setBoundDraft] = useState<Record<string, JsonValue> | null>(null);
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

  useEffect(() => {
    if (stage !== 'preview' && stage !== 'approval') return;
    setBoundDraft(null);
    setApproved(false);
    setStage('idle');
  // draftKey invalidates the local request preview before the job is submitted.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);

  const steps = useMemo(() => [
    { id: 'preview', label: '预览' },
    { id: 'approval', label: '确认' },
    { id: 'receipt', label: '执行' },
    { id: 'cancelled', label: '取消' },
  ] as const, []);
  const stageIndex = stage === 'idle' ? -1 : steps.findIndex((step) => step.id === stage);
  const actionable = availability.state === 'available';

  return (
    <div className="mgmt-workflow" data-availability={availability.state} data-stage={stage}>
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">{risk === 'R2' ? '谨慎确认' : '确认后执行'}</span>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        {stage === 'idle' && (availability.state === 'available' || availability.state === 'checking') ? (
          <Button
            disabled={!actionable}
            leadingIcon={<ShieldCheck size={15} />}
            loading={availability.state === 'checking'}
            onClick={() => {
              setBoundDraft({ ...draft });
              setStage('preview');
            }}
            size="small"
          >
            预览任务
          </Button>
        ) : null}
      </div>

      {availability.state !== 'available' && availability.state !== 'checking' && availability.reason ? (
        <InlineNotice title={availability.state === 'unsupported' ? '当前不可用' : '等待必要信息'} tone="warning">
          {availability.reason}
        </InlineNotice>
      ) : null}

      {stage !== 'idle' ? (
        <ol className="mgmt-workflow__steps" aria-label="知识任务进度">
          {steps.map((step, index) => (
            <li data-state={index < stageIndex ? 'complete' : index === stageIndex ? 'current' : 'pending'} key={step.id}>
              {index < stageIndex ? <Check size={13} /> : index === stageIndex ? <CircleDashed size={13} /> : <i />}
              {step.label}
            </li>
          ))}
        </ol>
      ) : null}

      {stage === 'preview' ? (
        <div className="mgmt-workflow__panel">
          <strong>任务请求预览</strong>
          <ul>{previewLines.map((line) => <li key={line}>{line}</li>)}</ul>
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => reset()} size="small" variant="quiet">取消</Button>
            <Button onClick={() => setStage('approval')} size="small" variant="primary">进入确认</Button>
          </div>
        </div>
      ) : null}

      {stage === 'approval' && boundDraft ? (
        <div className="mgmt-workflow__panel">
          <strong>确认启动这一个知识任务</strong>
          <label className="mgmt-workflow__confirm">
            <input checked={approved} onChange={(event) => setApproved(event.target.checked)} type="checkbox" />
            <span>只提交预览中的问题、模式和上下文</span>
          </label>
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => setStage('preview')} size="small" variant="quiet">返回预览</Button>
            <Button disabled={!approved} loading={startMutation.isPending} onClick={() => startMutation.mutate(boundDraft)} size="small" variant="primary">
              确认启动
            </Button>
          </div>
        </div>
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
            取消任务
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
    setApproved(false);
    setBoundDraft(null);
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
    throw new Error('服务端返回了无法验证的知识任务状态。');
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
