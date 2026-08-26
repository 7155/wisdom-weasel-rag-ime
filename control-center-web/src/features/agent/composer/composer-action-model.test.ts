import { describe, expect, it } from 'vitest';
import {
  composerActionLabel,
  composerBlockedReasonLabel,
  composerSubmitMode,
  projectComposerActionModel,
} from './composer-action-model';

const ready = {
  hasSession: true,
  draftHasContent: true,
  draftHasText: true,
  sending: false,
  stopping: false,
  modelChanging: false,
  busy: false,
  preferredBusyDelivery: 'steer' as const,
  capabilities: { queue: true },
};

describe('projectComposerActionModel', () => {
  it('sends when idle with a session and draft content', () => {
    const model = projectComposerActionModel(ready);
    expect(model).toMatchObject({
      primary: 'prompt',
      primaryDisabled: false,
      blockedReason: null,
      mode: 'idle',
    });
    expect(composerActionLabel(model.primary)).toBe('发送');
    expect(composerSubmitMode(model)).toBe('prompt');
  });

  it('falls queue back to followUp when the host has no queue capability', () => {
    const model = projectComposerActionModel({
      ...ready,
      busy: true,
      preferredBusyDelivery: 'queue',
      capabilities: { queue: false },
    });
    expect(model.effectiveBusyDelivery).toBe('followUp');
    expect(model.primary).toBe('followUp');
    expect(model.busyDeliveries).toEqual(['steer', 'followUp']);
    expect(composerActionLabel(model.primary)).toBe('当前执行完成后接续');
  });

  it('exposes queue as the primary busy action when capability is present', () => {
    const model = projectComposerActionModel({
      ...ready,
      busy: true,
      preferredBusyDelivery: 'queue',
    });
    expect(model.primary).toBe('queue');
    expect(model.busyDeliveries).toContain('queue');
    expect(composerActionLabel(model.primary)).toBe('排队，当前回合结束后发送');
  });

  it('names the anchor resolution honestly while historical editing opens', () => {
    // The host raises `sending` for this state too; the dedicated flag must
    // win so the reason never claims an earlier message is in flight.
    const model = projectComposerActionModel({ ...ready, sending: true, editResolving: true });
    expect(model).toMatchObject({
      primary: 'prompt',
      primaryDisabled: true,
      blockedReason: 'edit-resolving',
      mode: 'sending',
    });
    expect(composerBlockedReasonLabel(model.blockedReason)).toBe('正在定位历史消息');
    expect(composerSubmitMode(model)).toBeNull();
  });

  it('blocks with the same reasons the send label used to hide', () => {
    expect(composerBlockedReasonLabel(
      projectComposerActionModel({ ...ready, hasSession: false }).blockedReason,
    )).toBe('先选择或创建对话');
    expect(composerBlockedReasonLabel(
      projectComposerActionModel({ ...ready, draftHasContent: false }).blockedReason,
    )).toBe('先输入内容或添加附件');
    expect(composerBlockedReasonLabel(
      projectComposerActionModel({ ...ready, sending: true }).blockedReason,
    )).toBe('正在发送上一条消息');
    expect(composerBlockedReasonLabel(
      projectComposerActionModel({ ...ready, stopping: true }).blockedReason,
    )).toBe('正在停止本轮');
    expect(composerBlockedReasonLabel(
      projectComposerActionModel({ ...ready, modelChanging: true }).blockedReason,
    )).toBe('正在切换模型');
  });

  it('still names the action it is blocking, so a stop does not relabel the button', () => {
    const stoppingMidTurn = projectComposerActionModel({ ...ready, busy: true, stopping: true });

    expect(composerActionLabel(stoppingMidTurn.primary)).toBe('干预当前执行');
    expect(composerBlockedReasonLabel(stoppingMidTurn.blockedReason)).toBe('正在停止本轮');
    expect(composerSubmitMode(stoppingMidTurn)).toBeNull();
    expect(composerSubmitMode(stoppingMidTurn, { alternate: true })).toBeNull();
  });

  it('has no action to name when nothing is addressable', () => {
    const model = projectComposerActionModel({ ...ready, hasSession: false });

    expect(model.primary).toBe('none');
    expect(composerActionLabel(model.primary)).toBe('发送');
    expect(composerSubmitMode(model)).toBeNull();
  });

  it('refuses to queue an attachment-only draft, and says why', () => {
    const model = projectComposerActionModel({
      ...ready,
      busy: true,
      draftHasText: false,
      preferredBusyDelivery: 'queue',
    });

    expect(model.primary).toBe('queue');
    expect(model.primaryDisabled).toBe(true);
    expect(composerBlockedReasonLabel(model.blockedReason))
      .toBe('排队只保留文字，附件请用干预或接续直接发送');
    expect(composerSubmitMode(model)).toBeNull();
    // Alt+Enter names followUp, which does carry the attachment.
    expect(composerSubmitMode(model, { alternate: true })).toBe('followUp');
  });

  it('lets an attachment-only draft through the deliveries that carry it', () => {
    for (const delivery of ['steer', 'followUp'] as const) {
      const model = projectComposerActionModel({
        ...ready,
        busy: true,
        draftHasText: false,
        preferredBusyDelivery: delivery,
      });
      expect(model.primaryDisabled).toBe(false);
      expect(composerSubmitMode(model)).toBe(delivery);
    }
    expect(projectComposerActionModel({ ...ready, draftHasText: false }).primaryDisabled)
      .toBe(false);
  });

  it('keeps Alt+Enter as followUp while busy without changing the radio', () => {
    const model = projectComposerActionModel({
      ...ready,
      busy: true,
      preferredBusyDelivery: 'steer',
    });
    expect(composerSubmitMode(model)).toBe('steer');
    expect(composerSubmitMode(model, { alternate: true })).toBe('followUp');
  });
});
