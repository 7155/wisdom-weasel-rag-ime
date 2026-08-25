/* Vendored clean-room host boundary. See ./ATTRIBUTION.md.
 *
 * PAWOS owns conversation state in its Runtime-fed live stores, so the surface
 * consumes an already-reduced transcript rather than driving the transport
 * itself. These types stay the single named contract a PAWOS adapter has to
 * satisfy when it maps Runtime events into the surface model, and they are the
 * shape a non-PAWOS host of this package would implement. */

import type { AttachmentRef } from './model/types';

export interface SendPayload {
  conversationId: string;
  messageId: string;
  text: string;
  attachments: AttachmentRef[];
  parentMessageId?: string;
  mode: 'normal' | 'queued' | 'steer' | 'retry' | 'edit-retry';
}

export type AgentEvent =
  | { type: 'assistant-start'; messageId: string; timestamp?: number }
  | { type: 'thinking'; messageId: string; blockId: string; summary: string; detail?: string; status: 'running' | 'done' }
  | { type: 'text-delta'; messageId: string; blockId: string; delta: string }
  | { type: 'text-done'; messageId: string; blockId: string }
  | { type: 'tool'; messageId: string; blockId: string; name: string; summary?: string; input?: string; output?: string; status: 'pending' | 'running' | 'success' | 'error' | 'cancelled' }
  | { type: 'steer-read'; userMessageId: string }
  | { type: 'assistant-end'; messageId: string; stopReason?: string }
  | { type: 'error'; message: string };

export interface ConversationTransport {
  send(payload: SendPayload, signal: AbortSignal): AsyncIterable<AgentEvent>;
  stop?(conversationId: string): Promise<void> | void;
  /** Mid-turn steering. The current step may continue until the transport consumes this message. */
  steer?(payload: SendPayload): Promise<boolean> | boolean;
  /** Stronger escape hatch: end the current step so this steering message is consumed next. */
  interruptForSteer?(conversationId: string, userMessageId: string): Promise<boolean> | boolean;
  cancelSteer?(conversationId: string, userMessageId: string): Promise<boolean> | boolean;
  fork?(conversationId: string, fromMessageId: string): Promise<string> | string;
  rewind?(conversationId: string, toMessageId: string): Promise<boolean> | boolean;
}
