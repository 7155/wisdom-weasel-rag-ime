/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-workflow-state.v1.json
 */

export interface AgentWorkflowStateV1 {
  schemaVersion: 'rag-ime.agent-workflow-state.v1';
  ok: true;
  sessionId: string;
  todo: Todo;
  goal: Goal;
  actGate: ActGate;
}
export interface Todo {
  schemaVersion: 'rag-ime.agent-todo.v1';
  id: string;
  sessionId: string;
  revision: number;
  actor: string;
  updatedAtMs: number;
  roomLineage: RoomTodoLineage | null;
  /**
   * @maxItems 16
   */
  phases:
    | []
    | [TodoPhase]
    | [TodoPhase, TodoPhase]
    | [TodoPhase, TodoPhase, TodoPhase]
    | [TodoPhase, TodoPhase, TodoPhase, TodoPhase]
    | [TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase]
    | [TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase]
    | [TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase]
    | [TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase, TodoPhase]
    | [
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
      ]
    | [
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
      ]
    | [
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
      ]
    | [
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
      ]
    | [
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
      ]
    | [
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
      ]
    | [
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
      ]
    | [
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
        TodoPhase,
      ];
  counts: {
    total: number;
    pending: number;
    inProgress: number;
    blocked?: number;
    completed: number;
    abandoned: number;
  };
}
export interface RoomTodoLineage {
  schemaVersion: 'wisdom-weasel.room-todo-lineage.v1';
  roomId: string;
  rootId: string;
  taskId: string;
  workItemId: string;
  dispatchId: string;
  sessionId: string;
  participantId: string;
  generation: number;
  taskRevision: number;
  ownershipRevision: number;
  workItemRevision: number;
}
export interface TodoPhase {
  name: string;
  /**
   * @maxItems 100
   */
  tasks: TodoTask[];
}
export interface TodoTask {
  content: string;
  status: 'pending' | 'in_progress' | 'blocked' | 'completed' | 'abandoned';
  reason?: string;
}
export interface Goal {
  schemaVersion: 'rag-ime.agent-goal.v1';
  sessionId: string;
  configured: boolean;
  goalId: string;
  revision: number;
  objective: string;
  successCriteria: string;
  /**
   * @maxItems 20
   */
  evidenceExpectations:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
  status: 'active' | 'paused' | 'completed' | 'cancelled' | 'cleared';
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
  cancellationAudit: CancellationAudit | null;
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
export interface CancellationAudit {
  auditId: string;
  reason: string;
  cancelledBy: string;
  createdAtMs: number;
}
export interface ActGate {
  allowed: boolean;
  reason:
    | 'approved'
    | 'user_execution_request'
    | 'goal_paused'
    | 'goal_completed'
    | 'goal_cancelled'
    | 'goal_budget_exhausted';
  message: string;
  todoRevision: number;
  goalRevision: number;
}
