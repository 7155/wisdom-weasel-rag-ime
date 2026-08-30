/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-room-event-page.v1.json
 */

export interface AgentRoomEventPageV1 {
  schemaVersion: 'rag-ime.agent-room-event-page.v1';
  ok: true;
  roomId: string;
  /**
   * @maxItems 200
   */
  items: Event[];
  firstSequence: number;
  lastSequence: number;
  nextBeforeSequence: number;
  hasMore: boolean;
  retainedFirstSequence: number;
  retainedLastSequence: number;
  retainedPrefixTruncated: boolean;
}
export interface Event {
  schemaVersion: 'rag-ime.agent-room-event.v1';
  eventId: string;
  roomId: string;
  sequence: number;
  turnId: string;
  eventType:
    | 'user_message'
    | 'route_decision'
    | 'participant_status'
    | 'participant_delta'
    | 'participant_activity'
    | 'participant_message'
    | 'room_post'
    | 'room_config_changed'
    | 'topic_changed'
    | 'artifact_changed'
    | 'turn_completed'
    | 'turn_failed'
    | 'snapshot_required'
    | 'room_start_confirmation_required'
    | 'room_start_confirmation_confirmed'
    | 'room_start_confirmation_rejected';
  participantId: string | null;
  sourceSessionId: string;
  topicId?: string;
  createdAtMs: number;
  payload: {
    [k: string]: unknown;
  };
  resumeToken: string;
}
