/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-event.v1.json
 */

export interface AgentEventV1 {
  schemaVersion: 'rag-ime.agent-event.v1';
  eventId: string;
  sessionId: string;
  turnId: string;
  sequence: number;
  createdAtMs: number;
  eventType:
    | 'snapshot'
    | 'text_delta'
    | 'reasoning_summary'
    | 'status_changed'
    | 'session_configuration_changed'
    | 'session_command_invoked'
    | 'message_queue_updated'
    | 'workflow_changed'
    | 'lifecycle_cancellation_changed'
    | 'tool_started'
    | 'tool_progress'
    | 'tool_finished'
    | 'approval_required'
    | 'approval_resolved'
    | 'background_job_started'
    | 'background_job_progress'
    | 'background_job_completed'
    | 'background_job_failed'
    | 'background_job_cancelled'
    | 'memory_checkpointed'
    | 'memory_maintenance_updated'
    | 'user_input_required'
    | 'message_completed'
    | 'compaction_started'
    | 'compaction_completed'
    | 'turn_completed'
    | 'turn_failed'
    | 'snapshot_required'
    | 'heartbeat';
  payload: {
    [k: string]: unknown;
  };
  resumeToken: string;
  [k: string]: unknown;
}
