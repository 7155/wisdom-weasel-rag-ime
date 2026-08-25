import type { SideChatState } from "./types";

export type SideChatAction =
  | { type: "open" }
  | { type: "close" }
  | { type: "starting" }
  | { type: "ready" }
  | { type: "send"; text: string; id: string; timestamp: number }
  | { type: "assistant-delta"; text: string; id: string; timestamp: number }
  | { type: "turn-end" }
  | { type: "consume-queued" }
  | { type: "tool"; label: string | null }
  | { type: "error"; message: string }
  | { type: "clear" };

export function reduceSideChat(state: SideChatState, action: SideChatAction): SideChatState {
  switch (action.type) {
    case "open":
      return { ...state, open: true };
    case "close":
      return { ...state, open: false };
    case "starting":
      return { ...state, status: "starting", error: null };
    case "ready":
      return { ...state, status: "ready", error: null };
    case "send": {
      if (state.status === "thinking") {
        return { ...state, queued: action.text };
      }
      return {
        ...state,
        status: "thinking",
        error: null,
        messages: [...state.messages, { id: action.id, role: "user", text: action.text, timestamp: action.timestamp }],
      };
    }
    case "assistant-delta": {
      const last = state.messages[state.messages.length - 1];
      if (last?.role === "assistant" && last.id === action.id) {
        return {
          ...state,
          messages: state.messages.map(message =>
            message.id === action.id ? { ...message, text: message.text + action.text } : message,
          ),
        };
      }
      return {
        ...state,
        messages: [...state.messages, { id: action.id, role: "assistant", text: action.text, timestamp: action.timestamp }],
      };
    }
    case "turn-end":
      return { ...state, status: "ready", toolActivity: null };
    case "consume-queued":
      return { ...state, queued: null };
    case "tool":
      return { ...state, toolActivity: action.label };
    case "error":
      return { ...state, status: "error", error: action.message, toolActivity: null };
    case "clear":
      return { ...state, messages: [], queued: null, error: null, toolActivity: null, status: "ready" };
  }
}
