import { describe, expect, it } from 'vitest';

import {
  agentCommandReceiptFailure,
  MODEL_QUOTA_EXHAUSTED_TEXT,
  publicAgentErrorText,
} from './public-error';

describe('Agent command receipt public recovery', () => {
  it('turns an optional memory budget failure into a non-blocking message', () => {
    expect(publicAgentErrorText({
      payload: {
        errorCode: 'memory_bootstrap_budget_exceeded',
        error: 'memory bootstrap exceeded its strict character budget',
      },
    })).toBe('记忆召回本轮已跳过，消息仍可继续；下次会重新尝试。');
    expect(publicAgentErrorText(new Error('memory bootstrap exceeded its strict character budget')))
      .toBe('记忆召回本轮已跳过，消息仍可继续；下次会重新尝试。');
  });

  it('does not present a provider quota exhaustion as a local memory overflow', () => {
    expect(publicAgentErrorText(new Error('Codex error: The usage limit has been reached')))
      .toBe(MODEL_QUOTA_EXHAUSTED_TEXT);
    expect(publicAgentErrorText(new Error('memory curation packet exceeds the managed Session input limit')))
      .toBe('记忆召回本轮已跳过，消息仍可继续；下次会重新尝试。');
  });

  it('keeps the typed new-command recovery state and gives a direct resend action', () => {
    const error = {
      payload: {
        code: 'AGENT_COMMAND_CONFLICT',
        commandReceipt: {
          state: 'conflict',
          clientMessageId: 'local-command-id',
          causeCode: 'PAYLOAD_MISMATCH',
          recoveryState: 'new_command_required',
        },
      },
    };

    expect(agentCommandReceiptFailure(error)?.recoveryState)
      .toBe('new_command_required');
    expect(publicAgentErrorText(error))
      .toBe('这次发送内容已经变化，输入已保留；请直接重新发送一次。');
  });

  it('never exposes transport identity details for a generic command conflict', () => {
    const error = {
      payload: {
        code: 'AGENT_COMMAND_CONFLICT',
        commandReceipt: {
          state: 'conflict',
          clientMessageId: 'internal-id-must-stay-hidden',
          causeCode: 'PAYLOAD_MISMATCH',
        },
      },
    };

    const message = publicAgentErrorText(error);
    expect(message).toBe('这条消息没有发送；输入已保留，请直接重新发送一次。');
    expect(message).not.toContain('标识');
    expect(message).not.toContain('internal-id');
    expect(message).not.toContain('刷新');
  });
});
