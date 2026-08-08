import { describe, expect, it } from 'vitest';

import type { PendingRoomQuestion } from './room-question';
import { answerableRoomQuestion } from './room-question';
import type { RootProjection } from '@/contracts/room-kernel-reducer';

describe('answerableRoomQuestion', () => {
  const question: PendingRoomQuestion = {
    postId: 'post:question',
    roomId: 'room:1',
    rootId: 'root:1',
    sequence: 1,
    prompt: '还需要什么？',
    options: [],
  };

  it('fails closed when Kernel authority is absent or no longer answerable', () => {
    expect(answerableRoomQuestion(question, {})).toBeUndefined();
    expect(answerableRoomQuestion(question, {
      'root:1': root('blocked'),
    })).toBeUndefined();
  });

  it('keeps the control interactive only for the current answerable Root', () => {
    expect(answerableRoomQuestion(question, {
      'root:1': root('waiting'),
    })).toEqual(question);
  });
});

function root(state: RootProjection['state']): RootProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v3',
    rootId: 'root:1',
    roomId: 'room:1',
    generation: 0,
    state,
    facilitatorParticipantId: 'participant:1',
    reporterParticipantId: null,
    reporterSelectionReceiptId: null,
    requirementAnchorRef: 'requirement:1',
    createdByActorRef: 'user:local',
    terminalReceiptId: null,
    activeProfileRef: null,
    budgetPolicyRef: 'budget:1',
    independentReviewRequired: false,
    createdAtMs: 1,
    updatedAtMs: 1,
    isFinal: false,
  };
}
