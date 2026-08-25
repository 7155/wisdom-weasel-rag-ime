export type Id = string;

export type RunPhase =
  | "idle"
  | "sending"
  | "responding"
  | "stopping"
  | "error";

export type DeliveryStatus = "sending" | "sent" | "failed";
export type SteerReceiptState = "unread" | "read" | "settling" | "done";
export type ToolStatus = "pending" | "running" | "success" | "error" | "cancelled";

export interface AttachmentRef {
  id: Id;
  name: string;
  kind: "file" | "image" | "context";
  size?: number;
}

export interface ToolCallBlock {
  id: Id;
  kind: "tool";
  name: string;
  summary?: string;
  input?: string;
  output?: string;
  status: ToolStatus;
  startedAt?: number;
  endedAt?: number;
}

export interface ThinkingBlock {
  id: Id;
  kind: "thinking";
  summary: string;
  detail?: string;
  status: "running" | "done";
  startedAt?: number;
  endedAt?: number;
}

export interface TextBlock {
  id: Id;
  kind: "text";
  text: string;
  streaming?: boolean;
}

export type AssistantBlock = TextBlock | ThinkingBlock | ToolCallBlock;

export interface UserMessage {
  id: Id;
  role: "user";
  text: string;
  timestamp: number;
  attachments?: AttachmentRef[];
  deliveryStatus?: DeliveryStatus;
  queued?: boolean;
  awaitingPickup?: boolean;
  steerReceipt?: SteerReceiptState;
  parentId?: Id;
}

export interface AssistantMessage {
  id: Id;
  role: "assistant";
  timestamp: number;
  blocks: AssistantBlock[];
  parentId?: Id;
  stopReason?: string;
  error?: string;
}

export type TranscriptMessage = UserMessage | AssistantMessage;

export interface QueuedDraft {
  id: Id;
  text: string;
  attachments: AttachmentRef[];
  queuedAt: number;
  forConversationId: Id;
  queuedWhileBusy: boolean;
  queuedBehindPending: boolean;
}

export interface SideChatMessage {
  id: Id;
  role: "user" | "assistant";
  text: string;
  timestamp: number;
}

export type SideChatStatus = "idle" | "starting" | "ready" | "thinking" | "error";

export interface SideChatState {
  open: boolean;
  status: SideChatStatus;
  messages: SideChatMessage[];
  queued: string | null;
  error: string | null;
  toolActivity: string | null;
}

export interface DraftState {
  text: string;
  attachments: AttachmentRef[];
  editingMessageId: Id | null;
}

export interface ConversationState {
  conversationId: Id;
  phase: RunPhase;
  messages: TranscriptMessage[];
  queue: QueuedDraft[];
  draft: DraftState;
  activeAssistantId: Id | null;
  sideChat: SideChatState;
  lastError: string | null;
  branchLabel?: string;
}

export const EMPTY_DRAFT: DraftState = {
  text: "",
  attachments: [],
  editingMessageId: null,
};

export function createInitialConversationState(
  conversationId: Id,
  messages: TranscriptMessage[] = [],
): ConversationState {
  return {
    conversationId,
    phase: "idle",
    messages,
    queue: [],
    draft: { ...EMPTY_DRAFT },
    activeAssistantId: null,
    sideChat: {
      open: false,
      status: "idle",
      messages: [],
      queued: null,
      error: null,
      toolActivity: null,
    },
    lastError: null,
  };
}
