/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-room-snapshot.v1.json
 */

export interface AgentRoomSnapshotV1 {
  schemaVersion: 'rag-ime.agent-room-snapshot.v1';
  ok: true;
  room: Room;
  /**
   * @maxItems 2000
   */
  events: Event[];
  firstSequence: number;
  lastSequence: number;
  resumeToken: string;
  truncated: boolean;
}
export interface Room {
  schemaVersion: 'rag-ime.agent-room.v1';
  id: string;
  title: string;
  status: 'active' | 'archived';
  routingPolicy: 'manual_mentions' | 'moderator';
  moderatorParticipantId: string;
  /**
   * @maxItems 4
   */
  workspaceRoots:
    [] | [string] | [string, string] | [string, string, string] | [string, string, string, string];
  createdAtMs: number;
  updatedAtMs: number;
  lastEventSequence: number;
  /**
   * @minItems 2
   * @maxItems 4
   */
  participants:
    | [Participant, Participant]
    | [Participant, Participant, Participant]
    | [Participant, Participant, Participant, Participant];
}
export interface Participant {
  schemaVersion: 'rag-ime.agent-participant.v1';
  id: string;
  roomId: string;
  sessionId: string;
  roleId: string;
  roleVersion: string;
  displayName: string;
  collaborationRole: 'coordinator' | 'executor' | 'researcher';
  status: 'active' | 'muted' | 'removed';
  ordinal: number;
  createdAtMs: number;
  lastSpokeAtMs: number | null;
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
    | 'turn_completed'
    | 'turn_failed'
    | 'snapshot_required';
  participantId: string | null;
  sourceSessionId: string;
  createdAtMs: number;
  payload: {
    [k: string]: unknown;
  };
  resumeToken: string;
}
