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
  | null;

export interface ComposerActionModelInput {
  hasSession: boolean;
  draftHasContent: boolean;
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

  if (input.stopping) {
    return {
      primary: 'none',
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
      primary: 'none',
      primaryDisabled: true,
      effectiveBusyDelivery,
      busyDeliveries,
      blockedReason: 'sending',
      mode: 'sending',
    };
  }

  if (input.modelChanging) {
    return {
      primary: 'none',
      primaryDisabled: true,
      effectiveBusyDelivery,
      busyDeliveries,
      blockedReason: 'model-changing',
      mode: 'hard-blocked',
    };
  }

  if (!input.draftHasContent) {
    return {
      primary: input.busy ? effectiveBusyDelivery : 'prompt',
      primaryDisabled: true,
      effectiveBusyDelivery,
      busyDeliveries,
      blockedReason: 'empty-draft',
      mode: input.busy ? 'busy' : 'idle',
    };
  }

  if (input.busy) {
    return {
      primary: effectiveBusyDelivery,
      primaryDisabled: false,
      effectiveBusyDelivery,
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
  if (model.primaryDisabled || model.primary === 'none') return null;
  if (model.mode === 'busy' && options.alternate) return 'followUp';
  return model.primary;
}
