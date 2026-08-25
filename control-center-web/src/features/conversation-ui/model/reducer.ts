import { FRONTEND_QUEUE_CAP, mergeQueueAttachments, mergeQueueBackToDraft, reorderQueuedDrafts } from "./queue";
import { reduceSideChat, type SideChatAction } from "./sideChat";
import type {
  AssistantBlock,
  ConversationState,
  DraftState,
  QueuedDraft,
  TranscriptMessage,
  UserMessage,
} from "./types";

export type ConversationAction =
  | { type: "conversation/reset"; state: ConversationState }
  | { type: "draft/set-text"; text: string }
  | { type: "draft/set"; draft: DraftState }
  | { type: "draft/edit-message"; messageId: string; text: string; attachments?: DraftState["attachments"] }
  | { type: "draft/clear" }
  | { type: "draft/cancel-edit" }
  | { type: "run/phase"; phase: ConversationState["phase"] }
  | { type: "run/error"; message: string }
  | { type: "run/clear-error" }
  | { type: "message/append"; message: TranscriptMessage }
  | { type: "message/replace"; message: TranscriptMessage }
  | { type: "message/remove"; messageId: string }
  | { type: "message/remove-after"; messageId: string; includeSelf?: boolean }
  | { type: "message/mark-steer"; messageId: string; receipt: "unread" | "read" | "settling" | "done" }
  | { type: "message/update-assistant-block"; messageId: string; block: AssistantBlock }
  | { type: "message/append-assistant-text"; messageId: string; blockId: string; delta: string }
  | { type: "message/set-active-assistant"; messageId: string | null }
  | { type: "queue/enqueue"; item: QueuedDraft }
  | { type: "queue/remove"; id: string }
  | { type: "queue/edit"; id: string; text: string }
  | { type: "queue/reorder"; activeId: string; overId: string }
  | { type: "queue/promote"; id: string }
  | { type: "queue/clear" }
  | { type: "queue/restore-to-draft" }
  | { type: "queue/dequeue-head" }
  | { type: "side-chat"; action: SideChatAction };

function replaceMessage(
  messages: readonly TranscriptMessage[],
  message: TranscriptMessage,
): TranscriptMessage[] {
  const index = messages.findIndex(item => item.id === message.id);
  if (index < 0) return [...messages, message];
  const next = [...messages];
  next[index] = message;
  return next;
}

export function conversationReducer(
  state: ConversationState,
  action: ConversationAction,
): ConversationState {
  switch (action.type) {
    case "conversation/reset":
      return action.state;
    case "draft/set-text":
      return { ...state, draft: { ...state.draft, text: action.text } };
    case "draft/set":
      return { ...state, draft: action.draft };
    case "draft/edit-message":
      return {
        ...state,
        draft: {
          text: action.text,
          attachments: action.attachments ?? [],
          editingMessageId: action.messageId,
        },
      };
    case "draft/clear":
      return { ...state, draft: { text: "", attachments: [], editingMessageId: null } };
    case "draft/cancel-edit":
      return { ...state, draft: { text: "", attachments: [], editingMessageId: null } };
    case "run/phase":
      return { ...state, phase: action.phase, lastError: action.phase === "error" ? state.lastError : null };
    case "run/error":
      return { ...state, phase: "error", lastError: action.message };
    case "run/clear-error":
      return { ...state, phase: state.phase === "error" ? "idle" : state.phase, lastError: null };
    case "message/append":
      return { ...state, messages: [...state.messages, action.message] };
    case "message/replace":
      return { ...state, messages: replaceMessage(state.messages, action.message) };
    case "message/remove":
      return { ...state, messages: state.messages.filter(message => message.id !== action.messageId) };
    case "message/remove-after": {
      const index = state.messages.findIndex(item => item.id === action.messageId);
      if (index < 0) return state;
      const end = action.includeSelf ? index : index + 1;
      return {
        ...state,
        messages: state.messages.slice(0, end),
        activeAssistantId: null,
        phase: "idle",
      };
    }
    case "message/mark-steer":
      return {
        ...state,
        messages: state.messages.map(message =>
          message.id === action.messageId && message.role === "user"
            ? {
                ...message,
                awaitingPickup: action.receipt !== "done",
                steerReceipt: action.receipt,
              }
            : message,
        ),
      };
    case "message/update-assistant-block":
      return {
        ...state,
        messages: state.messages.map(message => {
          if (message.id !== action.messageId || message.role !== "assistant") return message;
          const index = message.blocks.findIndex(block => block.id === action.block.id);
          const blocks = [...message.blocks];
          if (index < 0) blocks.push(action.block);
          else blocks[index] = action.block;
          return { ...message, blocks };
        }),
      };
    case "message/append-assistant-text":
      return {
        ...state,
        messages: state.messages.map(message => {
          if (message.id !== action.messageId || message.role !== "assistant") return message;
          const index = message.blocks.findIndex(block => block.id === action.blockId && block.kind === "text");
          if (index < 0) {
            return {
              ...message,
              blocks: [...message.blocks, { id: action.blockId, kind: "text", text: action.delta, streaming: true }],
            };
          }
          const block = message.blocks[index];
          if (block?.kind !== "text") return message;
          const blocks = [...message.blocks];
          blocks[index] = { ...block, text: block.text + action.delta, streaming: true };
          return { ...message, blocks };
        }),
      };
    case "message/set-active-assistant":
      return { ...state, activeAssistantId: action.messageId };
    case "queue/enqueue":
      if (state.queue.length >= FRONTEND_QUEUE_CAP) return state;
      return { ...state, queue: [...state.queue, action.item] };
    case "queue/remove":
      return { ...state, queue: state.queue.filter(item => item.id !== action.id) };
    case "queue/edit":
      return {
        ...state,
        queue: state.queue.map(item => item.id === action.id ? { ...item, text: action.text } : item),
      };
    case "queue/reorder":
      return { ...state, queue: reorderQueuedDrafts(state.queue, action.activeId, action.overId) };
    case "queue/promote": {
      const item = state.queue.find(candidate => candidate.id === action.id);
      if (!item) return state;
      return { ...state, queue: [item, ...state.queue.filter(candidate => candidate.id !== action.id)] };
    }
    case "queue/clear":
      return { ...state, queue: [] };
    case "queue/restore-to-draft":
      return {
        ...state,
        draft: {
          ...state.draft,
          text: mergeQueueBackToDraft(state.queue, state.draft.text),
          attachments: mergeQueueAttachments(state.queue, state.draft.attachments),
        },
        queue: [],
      };
    case "queue/dequeue-head":
      return { ...state, queue: state.queue.slice(1) };
    case "side-chat":
      return { ...state, sideChat: reduceSideChat(state.sideChat, action.action) };
  }
}

export function findMessage(
  state: ConversationState,
  id: string,
): TranscriptMessage | undefined {
  return state.messages.find(message => message.id === id);
}

export function findUserBefore(
  state: ConversationState,
  assistantId: string,
): UserMessage | undefined {
  const index = state.messages.findIndex(message => message.id === assistantId);
  if (index < 0) return undefined;
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const message = state.messages[cursor];
    if (message?.role === "user") return message;
  }
  return undefined;
}
