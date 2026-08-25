import type { RoomMessageProjection, RoomProjectionState } from '@/contracts/room-reducer';
import type { TranscriptMessage, UserMessage, AssistantMessage, TextBlock } from '../model/types';

function userMessage(message: RoomMessageProjection): UserMessage {
  return {
    id: message.id,
    role: 'user',
    text: message.text,
    timestamp: message.createdAtMs,
    deliveryStatus: message.status === 'failed' ? 'failed' : message.status === 'streaming' ? 'sending' : 'sent',
  };
}

function assistantMessage(message: RoomMessageProjection): AssistantMessage {
  const blocks: TextBlock[] = [{
    id: `${message.id}:text`,
    kind: 'text',
    text: message.text || '',
    streaming: message.status === 'streaming',
  }];
  return {
    id: message.id,
    role: 'assistant',
    timestamp: message.createdAtMs,
    blocks,
    ...(message.status === 'failed' ? { error: '公开回复未完成' } : {}),
  };
}

/** Flatten the Room public ledger into the standalone conversation-ui transcript shape. */
export function mapRoomProjectionToTranscript(projection: RoomProjectionState): TranscriptMessage[] {
  const messages: TranscriptMessage[] = [];
  for (const messageId of projection.messageOrder) {
    const message = projection.messagesById[messageId];
    if (!message || message.visibility === 'internal') continue;
    messages.push(message.role === 'user' ? userMessage(message) : assistantMessage(message));
  }
  return messages;
}
