import { parseAgentEvent, parseRoomEvent } from '@/contracts/validators';

export function agentEventFixture(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
) {
  return parseAgentEvent({
    schemaVersion: 'rag-ime.agent-event.v1',
    eventId: `session-1:${sequence}`,
    sessionId: 'session-1',
    turnId: 'turn-1',
    sequence,
    createdAtMs: sequence * 10,
    eventType,
    payload: {
      messageId: 'turn-1:assistant',
      blockId: 'turn-1:assistant:text',
      ...payload,
    },
    resumeToken: `session-1:${sequence}`,
  });
}

export function roomEventFixture(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
) {
  return parseRoomEvent({
    schemaVersion: 'rag-ime.agent-room-event.v1',
    eventId: `room-1:${sequence}`,
    roomId: 'room-1',
    sequence,
    turnId: 'room-turn-1',
    eventType,
    participantId: 'participant-1',
    sourceSessionId: 'session-room-1',
    createdAtMs: sequence * 10,
    payload: { messageId: 'room-message-1', ...payload },
    resumeToken: `room-1:${sequence}`,
  });
}
