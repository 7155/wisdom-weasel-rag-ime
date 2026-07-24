import { CheckCircle2, Play, ShieldAlert } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Select,
} from '@/components/primitives';

export interface ManagedWorkDraft {
  requestId: string;
  objective: string;
  expectedOutput: string;
  acceptanceCriteria: string[];
  forbiddenAreas: string[];
  ownerParticipantId: string;
}

interface WorkParticipant {
  id: string;
  displayName: string;
  status: string;
}

export function RoomStartWorkDialog({
  open,
  participants,
  preferredOwnerParticipantId,
  submitting,
  onOpenChange,
  onSubmit,
}: {
  open: boolean;
  participants: WorkParticipant[];
  preferredOwnerParticipantId: string;
  submitting: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (draft: ManagedWorkDraft) => Promise<void>;
}) {
  const requestIdRef = useRef('');
  const [objective, setObjective] = useState('');
  const [expectedOutput, setExpectedOutput] = useState('');
  const [acceptanceText, setAcceptanceText] = useState('');
  const [forbiddenText, setForbiddenText] = useState('');
  const [ownerParticipantId, setOwnerParticipantId] = useState('');
  const [error, setError] = useState('');
  const activeParticipants = useMemo(
    () => participants.filter((participant) => participant.status === 'active'),
    [participants],
  );
  const acceptanceCriteria = lines(acceptanceText, 8);
  const forbiddenAreas = lines(forbiddenText, 8);
  const canSubmit = Boolean(
    objective.trim()
    && expectedOutput.trim()
    && acceptanceCriteria.length
    && ownerParticipantId,
  );

  useEffect(() => {
    if (!open) {
      requestIdRef.current = '';
      return;
    }
    requestIdRef.current ||= crypto.randomUUID();
    setOwnerParticipantId((current) => (
      activeParticipants.some((participant) => participant.id === current)
        ? current
        : activeParticipants.find(
          (participant) => participant.id === preferredOwnerParticipantId,
        )?.id ?? activeParticipants[0]?.id ?? ''
    ));
  }, [activeParticipants, open, preferredOwnerParticipantId]);

  async function submit(): Promise<void> {
    if (!canSubmit || submitting) return;
    setError('');
    try {
      await onSubmit({
        requestId: requestIdRef.current,
        objective: objective.trim(),
        expectedOutput: expectedOutput.trim(),
        acceptanceCriteria,
        forbiddenAreas,
        ownerParticipantId,
      });
      setObjective('');
      setExpectedOutput('');
      setAcceptanceText('');
      setForbiddenText('');
      setError('');
      requestIdRef.current = '';
      onOpenChange(false);
    } catch (submitError) {
      setError(
        submitError instanceof Error && submitError.message.trim()
          ? submitError.message
          : '任务暂时无法开始，请稍后重试。',
      );
    }
  }

  return <Dialog
    open={open}
    onOpenChange={(nextOpen) => {
      if (!submitting) {
        setError('');
        onOpenChange(nextOpen);
      }
    }}
  >
    <DialogContent className="room-start-work-dialog">
      <DialogHeader>
        <DialogTitle>确认并开始</DialogTitle>
        <DialogDescription>
          把刚才对齐的内容固定成受管任务。开始后，Agent 会持续工作，直到交付、交接、等待、阻塞或通过验收。
        </DialogDescription>
      </DialogHeader>
      <form
        id="room-start-work-form"
        className="room-start-work-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        {error ? <p className="room-dialog-error" role="alert">{error}</p> : null}
        <label className="room-create-field">
          <span>目标</span>
          <textarea
            aria-label="受管任务目标"
            maxLength={4_000}
            rows={3}
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="这次必须解决什么问题"
          />
        </label>
        <label className="room-create-field">
          <span>交付物</span>
          <input
            aria-label="受管任务交付物"
            maxLength={1_000}
            value={expectedOutput}
            onChange={(event) => setExpectedOutput(event.target.value)}
            placeholder="例如：实现、测试与可复核报告"
          />
        </label>
        <label className="room-create-field">
          <span>验收条件 <small>每行一项，最多 8 项</small></span>
          <textarea
            aria-label="受管任务验收条件"
            maxLength={4_000}
            rows={4}
            value={acceptanceText}
            onChange={(event) => setAcceptanceText(event.target.value)}
            placeholder={'真实测试通过\n结果可复核\n没有未处理的高风险问题'}
          />
        </label>
        <label className="room-create-field">
          <span>禁区与不可做 <small>可选，每行一项</small></span>
          <textarea
            aria-label="受管任务禁区"
            maxLength={3_000}
            rows={3}
            value={forbiddenText}
            onChange={(event) => setForbiddenText(event.target.value)}
            placeholder={'不要修改参考项目\n不要覆盖用户未提交改动'}
          />
        </label>
        <label className="room-create-field">
          <span>首位负责伙伴</span>
          <Select
            aria-label="首位负责伙伴"
            value={ownerParticipantId}
            onValueChange={setOwnerParticipantId}
            options={activeParticipants.map((participant) => ({
              value: participant.id,
              label: participant.displayName,
            }))}
          />
          <small className="room-start-work-owner-note">
            只决定谁先接手；伙伴仍是平级协作，可在执行中点名或正式交接。
          </small>
        </label>
        <div className="room-start-work-guards" aria-label="受管执行边界">
          <span><CheckCircle2 size={15} /><small>每次回答结束都会重新核对验收</small></span>
          <span><ShieldAlert size={15} /><small>取消、工作区和危险动作边界始终有效</small></span>
        </div>
      </form>
      <DialogFooter>
        <Button variant="quiet" disabled={submitting} onClick={() => onOpenChange(false)}>
          继续对齐
        </Button>
        <Button
          type="submit"
          form="room-start-work-form"
          variant="primary"
          loading={submitting}
          disabled={!canSubmit}
          leadingIcon={<Play size={15} />}
        >
          开始受管执行
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}

function lines(value: string, limit: number): string[] {
  return [...new Set(
    value
      .split(/\r?\n/u)
      .map((item) => item.trim().replace(/^[-*]\s+/u, ''))
      .filter(Boolean),
  )].slice(0, limit);
}
