/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-screen-state.v1.json
 */

export interface RoomScreenStateV1 {
  schemaVersion: 'wisdom-weasel.room-screen-state.v1';
  roomId: string;
  activeRootId: string | null;
  activeRootGeneration: number | null;
  phase:
    | 'idle'
    | 'alignment'
    | 'planning'
    | 'execution'
    | 'waiting'
    | 'blocked'
    | 'cancelling'
    | 'completed'
    | 'failed'
    | 'cancelled';
  waitReason: null | {
    kind: 'user' | 'participant' | 'external' | 'managed' | 'blocked';
    reason: string;
    requiresUserAction: boolean;
  };
  runnableFrontier: {
    taskIds: string[];
    dispatchIds: string[];
  };
  integrationReadiness: Readiness;
  reviewReadiness: Readiness;
  finalDeliveryPostId: string | null;
  recommendedNextAction:
    | 'align_requirement'
    | 'confirm_plan'
    | 'answer_question'
    | 'resolve_blocker'
    | 'continue_execution'
    | 'integrate_results'
    | 'complete_independent_review'
    | 'wait_for_progress'
    | 'start_new_task';
}
export interface Readiness {
  ready: boolean;
  reason: string | null;
  pendingTaskIds: string[];
}
