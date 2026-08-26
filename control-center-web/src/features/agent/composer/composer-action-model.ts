/**
 * Pure projection of what the composer may do right now.
 *
 * Adapted from `paw-agent-chat-ui-kit` `src/core/interaction/composer.ts`
 * (`projectComposerActionModel` only). PAW vocabulary: prompt / steer /
 * followUp / queue. Runtime interrupt/guide commands are deliberately absent.
 */

export type ComposerSubmitMode = 'prompt' | 'steer' | 'followUp' | 'queue';
export type ComposerBusyDelivery = Exclude<ComposerSubmitMode, 'prompt'>;
export type ComposerPrimaryAction = 'none' | ComposerSubmitMode;

export type ComposerBlockedReason =
  | 'stopping'
  | 'no-session'
  | 'sending'
  | 'model-changing'
  | 'empty-draft'
  | 'queue-needs-text'
  | null;

export interface ComposerActionModelInput {
  hasSession: boolean;
  draftHasContent: boolean;
  /** Text alone, without attachments. The client-side queue holds a string;
   *  the Runtime deliveries carry the whole draft. */
  draftHasText: boolean;
  draftHasAttachments: boolean;
  sending: boolean;
  stopping: boolean;
  modelChanging: boolean;
  busy: boolean;
  preferredBusyDelivery: ComposerBusyDelivery;
  capabilities: {
    queue: boolean;
  };
}

export interface ComposerActionModel {
  primary: ComposerPrimaryAction;
  primaryDisabled: boolean;
  effectiveBusyDelivery: ComposerBusyDelivery;
  /** Busy delivery modes the host may expose in the radio group. */
  busyDeliveries: readonly ComposerBusyDelivery[];
  blockedReason: ComposerBlockedReason;
  mode: 'hard-blocked' | 'idle' | 'busy' | 'sending' | 'stopping';
}

export function projectComposerActionModel(
  input: ComposerActionModelInput,
): ComposerActionModel {
  const busyDeliveries: ComposerBusyDelivery[] = input.capabilities.queue
    ? ['steer', 'followUp', 'queue']
    : ['steer', 'followUp'];
  const effectiveBusyDelivery: ComposerBusyDelivery =
    input.preferredBusyDelivery === 'queue' && !input.capabilities.queue
      ? 'followUp'
      : input.preferredBusyDelivery;

  /* A blocked action still names what it would do: the button reads
     "干预当前执行（正在停止本轮）", never a bare "发送". Only `none` — nothing
     addressable at all — has no action to name. */
  const blockedPrimary: ComposerPrimaryAction = input.busy ? effectiveBusyDelivery : 'prompt';

  if (input.stopping) {
    return {
      primary: blockedPrimary,
      primaryDisabled: true,
      effectiveBusyDelivery,
      busyDeliveries,
      blockedReason: 'stopping',
      mode: 'stopping',
    };
  }

  if (!input.hasSession) {
    return {
      primary: 'none',
      primaryDisabled: true,
      effectiveBusyDelivery,
      busyDeliveries,
      blockedReason: 'no-session',
      mode: 'hard-blocked',
    };
  }

  if (input.sending) {
    return {
      primary: blockedPrimary,
      primaryDisabled: true,
      effectiveBusyDelivery,
      busyDeliveries,
      blockedReason: 'sending',
      mode: 'sending',
    };
  }

  if (input.modelChanging) {
    return {
      primary: blockedPrimary,
      primaryDisabled: true,
      effectiveBusyDelivery,
      busyDeliveries,
      blockedReason: 'model-changing',
      mode: 'hard-blocked',
    };
  }

  if (!input.draftHasContent) {
    return {
      primary: blockedPrimary,
      primaryDisabled: true,
      effectiveBusyDelivery,
      busyDeliveries,
      blockedReason: 'empty-draft',
      mode: input.busy ? 'busy' : 'idle',
    };
  }

  if (input.busy) {
    /* The local follow-up hold is text-only. Any draft containing attachments
       stays intact by falling through to Pi's native follow-up; an
       attachment-only draft also avoids turning Enter into a silent no-op. */
    const localQueueCannotCarryDraft = effectiveBusyDelivery === 'queue'
      && (!input.draftHasText || input.draftHasAttachments);
    const deliverableBusyDelivery = localQueueCannotCarryDraft
      ? 'followUp'
      : effectiveBusyDelivery;
    return {
      primary: deliverableBusyDelivery,
      primaryDisabled: false,
      effectiveBusyDelivery: deliverableBusyDelivery,
      busyDeliveries,
      blockedReason: null,
      mode: 'busy',
    };
  }

  return {
    primary: 'prompt',
    primaryDisabled: false,
    effectiveBusyDelivery,
    busyDeliveries,
    blockedReason: null,
    mode: 'idle',
  };
}

export function composerActionLabel(primary: ComposerPrimaryAction): string {
  if (primary === 'steer') return '干预当前执行';
  if (primary === 'queue') return '排队，当前回合结束后发送';
  if (primary === 'followUp') return '当前执行完成后接续';
  if (primary === 'none') return '发送';
  return '发送';
}

export function composerBlockedReasonLabel(reason: ComposerBlockedReason): string {
  if (reason === 'stopping') return '正在停止本轮';
  if (reason === 'no-session') return '先选择或创建对话';
  if (reason === 'sending') return '正在发送上一条消息';
  if (reason === 'model-changing') return '正在切换模型';
  if (reason === 'empty-draft') return '先输入内容或添加附件';
  if (reason === 'queue-needs-text') return '排队只保留文字，附件请用干预或接续直接发送';
  return '';
}

/**
 * Map the projected primary action to a submit mode. Alt+Enter while busy
 * prefers followUp without changing the radio selection.
 */
export function composerSubmitMode(
  model: ComposerActionModel,
  options: { alternate?: boolean } = {},
): ComposerSubmitMode | null {
  if (model.mode === 'busy' && options.alternate) {
    // The only block Alt+Enter escapes is the one it removes by naming a
    // different delivery: followUp carries what the queue could not hold.
    if (!model.primaryDisabled || model.blockedReason === 'queue-needs-text') {
      return 'followUp';
    }
    return null;
  }
  if (model.primaryDisabled || model.primary === 'none') return null;
  return model.primary;
}
