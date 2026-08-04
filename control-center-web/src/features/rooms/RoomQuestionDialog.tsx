import * as RadioGroup from '@radix-ui/react-radio-group';
import { Check, MessageSquareText, PencilLine } from 'lucide-react';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

import { Button, Field, TextArea } from '@/components/primitives';
import type { RoomMessageQuestionProjection } from '@/contracts/room-reducer';
import type { RoomQuestionAnswerKind } from './room-question';

export function RoomQuestionDialog({
  active,
  question,
  onSubmit,
}: {
  active?: boolean;
  question: RoomMessageQuestionProjection;
  onSubmit?: (value: string, answerKind: RoomQuestionAnswerKind) => Promise<boolean>;
}) {
  const optionIdPrefix = useId();
  const answerId = useId();
  const [selectedValue, setSelectedValue] = useState('');
  const [freeformValue, setFreeformValue] = useState('');
  const [customAnswer, setCustomAnswer] = useState(question.options.length === 0);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const submittingRef = useRef(false);
  const firstOptionRef = useRef<HTMLButtonElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  const hasOptions = question.options.length > 0;
  const authoritative = active ?? Boolean(onSubmit);
  const stale = question.status === 'pending' && !authoritative;
  const interactive = question.status === 'pending' && authoritative && Boolean(onSubmit);
  const answerValue = customAnswer || !hasOptions ? freeformValue : selectedValue;
  const questionFocusKey = `${question.prompt}\u001f${question.options
    .map((option) => option.value)
    .join('\u001f')}`;

  useEffect(() => {
    setSelectedValue('');
    setFreeformValue('');
    setCustomAnswer(question.options.length === 0);
    setSubmitting(false);
    submittingRef.current = false;
    setSubmitError('');
  }, [question.prompt, question.status, question.options.length]);

  useEffect(() => {
    if (!interactive) return undefined;
    const frame = window.requestAnimationFrame(() => {
      (hasOptions && !customAnswer
        ? firstOptionRef.current
        : textAreaRef.current
      )?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [customAnswer, hasOptions, interactive, questionFocusKey]);

  async function submitValue(
    value: string,
    answerKind: RoomQuestionAnswerKind,
  ): Promise<void> {
    if (!interactive || !onSubmit || !value.trim() || submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    setSubmitError('');
    const accepted = await onSubmit(value, answerKind).catch(() => false);
    if (!accepted) {
      setSubmitError('这次还没有送达，请稍后再确认一次。');
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    void submitValue(
      answerValue,
      hasOptions && !customAnswer ? 'option' : 'custom',
    );
  }

  return <section
    aria-label={`需要回答：${question.prompt}`}
    aria-live={interactive ? 'polite' : undefined}
    aria-atomic={interactive || undefined}
    aria-busy={submitting || undefined}
    className="room-question-card"
    data-state={stale ? 'stale' : question.status}
  >
    <header>
      <span><MessageSquareText size={16} aria-hidden="true" /></span>
      <span>
        <small>{question.status === 'pending' && !stale
          ? hasOptions ? '选择后确认' : '等待你的回答'
          : stale
            ? '问题已失效'
            : question.status === 'answered'
              ? '已收到回答'
              : '问题记录'}</small>
        <strong>{question.prompt}</strong>
      </span>
    </header>
    {question.status === 'answered' ? <QuestionAnsweredNotice /> : null}
    {question.status === 'superseded' ? <p className="room-question-card__superseded">这项问题已由后续问题替代。</p> : null}
    {stale ? <p className="room-question-card__stale">这项问题已不再是当前可回答的问题。</p> : null}
    {interactive ? <form className="room-question-card__form" onSubmit={submit}>
      {hasOptions && !customAnswer ? <RadioGroup.Root
        aria-label="可选回答"
        className="room-question-card__options"
        disabled={submitting}
        onValueChange={(value) => {
          setSelectedValue(value);
          setSubmitError('');
        }}
        value={selectedValue}
      >
        {question.options.map((option, index) => {
          const labelId = `${optionIdPrefix}-label-${index}`;
          const descriptionId = option.description
            ? `${optionIdPrefix}-description-${index}`
            : undefined;
          return <RadioGroup.Item
            aria-describedby={descriptionId}
            aria-labelledby={labelId}
            className="room-question-card__option"
            data-pending={submitting && selectedValue === option.value ? 'true' : undefined}
            onClick={() => {
              setSelectedValue(option.value);
              setSubmitError('');
            }}
            key={option.value}
            ref={index === 0 ? firstOptionRef : undefined}
            value={option.value}
          >
            <span className="room-question-card__control" aria-hidden="true">
              <RadioGroup.Indicator><Check size={13} /></RadioGroup.Indicator>
            </span>
            <span>
              <span id={labelId}><strong>{option.label}</strong>{option.recommended ? <em>推荐</em> : null}</span>
              {option.description ? <small id={descriptionId}>{option.description}</small> : null}
            </span>
          </RadioGroup.Item>;
        })}
      </RadioGroup.Root> : <Field
        className="room-question-card__answer"
        description={hasOptions ? '以上选项都不合适时，用自己的话补充。' : '用自己的话回答，伙伴会继续同一项任务。'}
        htmlFor={answerId}
        label="你的回答"
        required
      >
        <TextArea
          aria-describedby={`${answerId}-description`}
          disabled={submitting}
          id={answerId}
          ref={textAreaRef}
          maxLength={8_000}
          onChange={(event) => {
            setFreeformValue(event.target.value);
            setSubmitError('');
          }}
          placeholder="写下需要伙伴遵循的选择或补充信息"
          rows={3}
          value={freeformValue}
        />
      </Field>}
      {submitError ? <p className="room-question-card__error" role="alert">{submitError}</p> : null}
      <footer>
        {hasOptions ? <Button
          disabled={submitting}
          leadingIcon={<PencilLine size={14} />}
          onClick={() => {
            const showCustomAnswer = !customAnswer;
            setCustomAnswer(showCustomAnswer);
            setSubmitError('');
            if (showCustomAnswer) {
              window.requestAnimationFrame(() => textAreaRef.current?.focus());
            }
          }}
          size="small"
          type="button"
          variant="quiet"
        >{customAnswer ? '返回选项' : '其他'}</Button> : <span />}
        <Button
          disabled={!answerValue.trim() || submitting}
          loading={submitting}
          size="small"
          type="submit"
          variant="primary"
        >{hasOptions && !customAnswer ? '确认并发送' : '发送回答'}</Button>
      </footer>
    </form> : null}
  </section>;
}

function QuestionAnsweredNotice() {
  return <div className="room-question-card__resolved" role="status">
    <Check size={15} aria-hidden="true" />
    <span>
      <small>已锁定</small>
      <strong>回答保留在下一条用户消息中</strong>
    </span>
  </div>;
}
