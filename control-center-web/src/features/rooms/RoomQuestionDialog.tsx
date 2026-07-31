import * as RadioGroup from '@radix-ui/react-radio-group';
import { Check, MessageSquareText } from 'lucide-react';
import { useEffect, useId, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react';

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/primitives';
import type { PendingRoomQuestion } from './room-question';

export function RoomQuestionDialog({
  open,
  question,
  onCancel,
  onCloseAutoFocus,
  onSubmit,
}: {
  open: boolean;
  question?: PendingRoomQuestion;
  onCancel: () => void;
  onCloseAutoFocus: () => void;
  onSubmit: (value: string) => Promise<boolean>;
}) {
  const optionIdPrefix = useId();
  const [selectedValue, setSelectedValue] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');

  useEffect(() => {
    setSelectedValue('');
    setSubmitting(false);
    setSubmitError('');
  }, [question?.postId]);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!selectedValue || submitting) return;
    setSubmitting(true);
    setSubmitError('');
    const accepted = await onSubmit(selectedValue).catch(() => false);
    if (!accepted) {
      setSubmitError('回答没有发送，请检查连接后重试。');
      setSubmitting(false);
    }
  }

  function selectWithKeyboard(
    event: ReactKeyboardEvent<HTMLButtonElement>,
    index: number,
  ): void {
    if (!question || submitting) return;
    const lastIndex = question.options.length - 1;
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? lastIndex
        : event.key === 'ArrowDown' || event.key === 'ArrowRight'
          ? (index + 1) % question.options.length
          : event.key === 'ArrowUp' || event.key === 'ArrowLeft'
            ? (index - 1 + question.options.length) % question.options.length
            : -1;
    if (nextIndex < 0) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedValue(question.options[nextIndex]!.value);
    setSubmitError('');
    document.getElementById(`${optionIdPrefix}-option-${nextIndex}`)?.focus();
  }

  return <Dialog open={open && Boolean(question)} onOpenChange={(nextOpen) => {
    if (!nextOpen && !submitting) onCancel();
  }}>
    <DialogContent
      className="room-question-dialog"
      hideClose
      onCloseAutoFocus={(event) => {
        event.preventDefault();
        onCloseAutoFocus();
      }}
      onEscapeKeyDown={(event) => { if (submitting) event.preventDefault(); }}
      onInteractOutside={(event) => event.preventDefault()}
    >
      <DialogHeader>
        <span className="room-question-dialog__eyebrow"><MessageSquareText size={16} aria-hidden="true" />等待你的选择</span>
        <DialogTitle>伙伴需要你确认下一步</DialogTitle>
        <DialogDescription>{question?.prompt}</DialogDescription>
      </DialogHeader>
      {question ? <form className="room-question-dialog__form" onSubmit={(event) => void submit(event)}>
        <RadioGroup.Root
          aria-label="可选回答"
          className="room-question-dialog__options"
          disabled={submitting}
          onValueChange={(value) => { setSelectedValue(value); setSubmitError(''); }}
          value={selectedValue}
        >
          {question.options.map((option, index) => {
            const labelId = `${optionIdPrefix}-label-${index}`;
            const descriptionId = option.description ? `${optionIdPrefix}-description-${index}` : undefined;
            const optionId = `${optionIdPrefix}-option-${index}`;
            return <RadioGroup.Item
              aria-describedby={descriptionId}
              aria-labelledby={labelId}
              id={optionId}
              className="room-question-option"
              key={option.value}
              onKeyDown={(event) => selectWithKeyboard(event, index)}
              value={option.value}
            >
              <span className="room-question-option__control" aria-hidden="true"><RadioGroup.Indicator><Check size={14} /></RadioGroup.Indicator></span>
              <span className="room-question-option__copy">
                <span id={labelId}><strong>{option.label}</strong>{option.recommended ? <em>推荐</em> : null}</span>
                {option.description ? <small id={descriptionId}>{option.description}</small> : null}
              </span>
            </RadioGroup.Item>;
          })}
        </RadioGroup.Root>
        <p className="room-question-dialog__hint">推荐项只是提示，不会替你选择或自动发送。</p>
        {submitError ? <p className="room-question-dialog__error" role="alert">{submitError}</p> : null}
        <DialogFooter>
          <Button disabled={submitting} onClick={onCancel} variant="quiet">取消</Button>
          <Button disabled={!selectedValue} loading={submitting} type="submit" variant="primary">发送回答</Button>
        </DialogFooter>
      </form> : null}
    </DialogContent>
  </Dialog>;
}
