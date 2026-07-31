import { describe, expect, it } from 'vitest';

import {
  approvalDecisionView,
  approvalDecisionReasonLabel,
  approvalNeedsHumanDecision,
} from './approval-decision';

describe('approvalDecisionView', () => {
  it('recognizes a nested model decision as unattended and preserves bounded evidence', () => {
    const payload = {
      approvalId: 'approval-1',
      decisionMode: 'model',
      approvalDecisionReceiptId: 'approval-model-decision:1',
      approvalModelDecision: {
        decision: 'deny',
        status: 'decided',
        model: 'openai-codex/gpt-5.6-luna',
        reasonCodes: ['destructive_command', 'irreversible_effect'],
        rationaleSummary: '删除会造成不可逆影响。',
        contextKind: 'room',
        contextId: 'room-1',
        historyEntryCount: 3,
      },
    };

    expect(approvalDecisionView(payload)).toEqual({
      mode: 'model',
      automatic: true,
      decision: 'deny',
      status: 'decided',
      model: 'openai-codex/gpt-5.6-luna',
      receiptId: 'approval-model-decision:1',
      reasonCodes: ['destructive_command', 'irreversible_effect'],
      rationaleSummary: '删除会造成不可逆影响。',
      contextKind: 'room',
      contextId: 'room-1',
      historyEntryCount: 3,
    });
    expect(approvalDecisionReasonLabel('irreversible_effect')).toBe('影响不可逆');
    expect(approvalNeedsHumanDecision(payload)).toBe(false);
  });

  it('keeps a pending full-automation approval model-owned before a verdict exists', () => {
    const payload = {
      approvalId: 'approval-model-pending',
      state: 'pending',
      preview: {
        approvalArbitration: {
          mode: 'model',
          status: 'running',
          model: 'openai-codex/gpt-5.6-luna',
        },
      },
    };

    expect(approvalDecisionView(payload)).toMatchObject({
      mode: 'model',
      automatic: true,
      decision: '',
      status: 'running',
      model: 'openai-codex/gpt-5.6-luna',
    });
    expect(approvalNeedsHumanDecision(payload)).toBe(false);
  });

  it('keeps an ordinary pending approval human-owned', () => {
    expect(approvalNeedsHumanDecision({
      approvalId: 'approval-human-1',
      payloadSha256: 'a'.repeat(64),
      state: 'pending',
    })).toBe(true);
  });

  it('reads policy automation from a public Tool result without trusting prose', () => {
    expect(approvalDecisionView({
      result: {
        decisionMode: 'policy',
        automatic: true,
        summary: 'this text is not used for authority',
      },
    })).toMatchObject({ mode: 'policy', automatic: true });
  });
});
