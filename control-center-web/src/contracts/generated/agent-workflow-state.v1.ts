/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-workflow-state.v1.json
 */

export interface AgentWorkflowStateV1 {
  schemaVersion: 'rag-ime.agent-workflow-state.v1';
  ok: true;
  sessionId: string;
  plan: Plan;
  goal: Goal;
  actGate: ActGate;
}
export interface Plan {
  schemaVersion: 'rag-ime.agent-plan.v2';
  id: string;
  sessionId: string;
  revision: number;
  title: string;
  status: 'draft' | 'review' | 'approved' | 'executing' | 'completed' | 'cancelled';
  actor: string;
  note: string;
  updatedAtMs: number;
  editable: boolean;
  actApproved: boolean;
  /**
   * @maxItems 100
   */
  items: PlanItem[];
  counts: {
    total: number;
    pending: number;
    inProgress: number;
    completed: number;
  };
}
export interface PlanItem {
  id: string;
  title: string;
  status: 'pending' | 'in_progress' | 'completed';
  position: number;
  sequence: number;
  updatedAtMs: number;
}
export interface Goal {
  schemaVersion: 'rag-ime.agent-goal.v1';
  sessionId: string;
  configured: boolean;
  goalId: string;
  revision: number;
  objective: string;
  status: 'active' | 'paused' | 'completed' | 'cleared';
  budget: {
    tokenLimit: number | null;
    timeLimitMs: number | null;
  };
  usage: {
    tokens: number;
    elapsedMs: number;
  };
  remaining: {
    tokens: number | null;
    timeMs: number | null;
  };
  budgetExceeded: boolean;
  completionAudit: CompletionAudit | null;
  updatedAtMs: number;
}
export interface CompletionAudit {
  auditId: string;
  summary: string;
  /**
   * @minItems 1
   * @maxItems 20
   */
  evidence:
    | [Evidence]
    | [Evidence, Evidence]
    | [Evidence, Evidence, Evidence]
    | [Evidence, Evidence, Evidence, Evidence]
    | [Evidence, Evidence, Evidence, Evidence, Evidence]
    | [Evidence, Evidence, Evidence, Evidence, Evidence, Evidence]
    | [Evidence, Evidence, Evidence, Evidence, Evidence, Evidence, Evidence]
    | [Evidence, Evidence, Evidence, Evidence, Evidence, Evidence, Evidence, Evidence]
    | [Evidence, Evidence, Evidence, Evidence, Evidence, Evidence, Evidence, Evidence, Evidence]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ]
    | [
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
        Evidence,
      ];
  completedBy: string;
  createdAtMs: number;
}
export interface Evidence {
  kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
  summary: string;
  reference: string;
}
export interface ActGate {
  allowed: boolean;
  reason:
    | 'approved'
    | 'plan_required'
    | 'plan_not_approved'
    | 'plan_completed'
    | 'plan_cancelled'
    | 'goal_paused'
    | 'goal_completed'
    | 'goal_budget_exhausted';
  message: string;
}
