import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import { createQueuedDraft, FRONTEND_QUEUE_CAP } from "../model/queue";
import {
  conversationReducer,
  findMessage,
  findUserBefore,
  type ConversationAction,
} from "../model/reducer";
import {
  createInitialConversationState,
  type AssistantMessage,
  type ConversationState,
  type TranscriptMessage,
  type UserMessage,
} from "../model/types";
import type {
  AgentEvent,
  ConversationTransport,
  SendPayload,
} from "../transport";

function uid(prefix: string): string {
  return `${prefix}-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;
}

export type BusySubmitMode = "queue" | "steer";

export interface ConversationController {
  state: ConversationState;
  capabilities: {
    steering: boolean;
    interrupt: boolean;
    fork: boolean;
    rewind: boolean;
    sideChat: boolean;
  };
  setDraft(text: string): void;
  cancelEditing(): void;
  dismissError(): void;
  submit(mode?: "auto" | BusySubmitMode): Promise<boolean>;
  stop(): Promise<void>;
  removeQueued(id: string): void;
  editQueued(id: string, text: string): void;
  reorderQueued(activeId: string, overId: string): void;
  clearQueue(): void;
  sendQueuedNow(id: string): Promise<boolean>;
  interruptSteer(messageId: string): Promise<boolean>;
  cancelAndEditSteer(messageId: string): Promise<boolean>;
  editAndRetry(messageId: string): void;
  retryAssistant(messageId: string): Promise<boolean>;
  forkFrom(messageId: string): Promise<string | null>;
  rewindTo(messageId: string): Promise<boolean>;
  toggleSideChat(force?: boolean): void;
  clearSideChat(): void;
  sendSideChat(text: string): Promise<boolean>;
}

const ConversationContext = createContext<ConversationController | null>(null);

export interface ConversationProviderProps {
  conversationId: string;
  transport: ConversationTransport;
  initialMessages?: TranscriptMessage[];
  children: ReactNode;
  onForkCreated?: (forkConversationId: string, fromMessageId: string) => void;
}

export function ConversationProvider({
  conversationId,
  transport,
  initialMessages = [],
  children,
  onForkCreated,
}: ConversationProviderProps) {
  const [state, rawDispatch] = useReducer(
    conversationReducer,
    undefined,
    () => createInitialConversationState(conversationId, initialMessages),
  );
  const stateRef = useRef(state);
  // Keep the imperative event-consumer view in lock-step with reducer actions.
  // Streaming transports can emit multiple events before React commits a render;
  // reading only the last committed state would otherwise lose text-done/tool transitions.
  const dispatch = useCallback((action: ConversationAction) => {
    stateRef.current = conversationReducer(stateRef.current, action);
    rawDispatch(action);
  }, []);
  const activeAbort = useRef<AbortController | null>(null);
  const sideAbort = useRef<AbortController | null>(null);
  const activeConversationId = useRef(conversationId);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    if (activeConversationId.current === conversationId) return;
    activeAbort.current?.abort();
    sideAbort.current?.abort();
    activeAbort.current = null;
    sideAbort.current = null;
    activeConversationId.current = conversationId;
    const next = createInitialConversationState(conversationId, initialMessages);
    dispatch({ type: "conversation/reset", state: next });
  }, [conversationId, dispatch, initialMessages]);

  const markSteerRead = useCallback((messageId: string) => {
    dispatch({ type: "message/mark-steer", messageId, receipt: "read" });
    window.setTimeout(() => {
      dispatch({ type: "message/mark-steer", messageId, receipt: "settling" });
      window.setTimeout(() => {
        dispatch({ type: "message/mark-steer", messageId, receipt: "done" });
      }, 400);
    }, 1400);
  }, []);

  const consumeEvent = useCallback((event: AgentEvent) => {
    switch (event.type) {
      case "assistant-start": {
        const assistant: AssistantMessage = {
          id: event.messageId,
          role: "assistant",
          timestamp: event.timestamp ?? Date.now(),
          blocks: [],
        };
        dispatch({ type: "message/append", message: assistant });
        dispatch({ type: "message/set-active-assistant", messageId: event.messageId });
        dispatch({ type: "run/phase", phase: "responding" });
        break;
      }
      case "thinking":
        dispatch({
          type: "message/update-assistant-block",
          messageId: event.messageId,
          block: {
            id: event.blockId,
            kind: "thinking",
            summary: event.summary,
            detail: event.detail,
            status: event.status,
          },
        });
        break;
      case "text-delta":
        dispatch({
          type: "message/append-assistant-text",
          messageId: event.messageId,
          blockId: event.blockId,
          delta: event.delta,
        });
        break;
      case "text-done": {
        const current = stateRef.current.messages.find(message => message.id === event.messageId);
        if (current?.role === "assistant") {
          const block = current.blocks.find(candidate => candidate.id === event.blockId);
          if (block?.kind === "text") {
            dispatch({
              type: "message/update-assistant-block",
              messageId: event.messageId,
              block: { ...block, streaming: false },
            });
          }
        }
        break;
      }
      case "tool":
        dispatch({
          type: "message/update-assistant-block",
          messageId: event.messageId,
          block: {
            id: event.blockId,
            kind: "tool",
            name: event.name,
            summary: event.summary,
            input: event.input,
            output: event.output,
            status: event.status,
          },
        });
        break;
      case "steer-read":
        markSteerRead(event.userMessageId);
        break;
      case "assistant-end": {
        const current = stateRef.current.messages.find(message => message.id === event.messageId);
        if (current?.role === "assistant") {
          dispatch({
            type: "message/replace",
            message: { ...current, stopReason: event.stopReason },
          });
        }
        dispatch({ type: "message/set-active-assistant", messageId: null });
        break;
      }
      case "error":
        dispatch({ type: "run/error", message: event.message });
        break;
    }
  }, [markSteerRead]);

  const runPayload = useCallback(async (
    payload: SendPayload,
    appendUser: boolean,
  ): Promise<boolean> => {
    if (activeAbort.current) return false;

    if (appendUser) {
      const user: UserMessage = {
        id: payload.messageId,
        role: "user",
        text: payload.text,
        attachments: payload.attachments,
        timestamp: Date.now(),
        deliveryStatus: "sent",
      };
      dispatch({ type: "message/append", message: user });
    }

    dispatch({ type: "run/phase", phase: "sending" });
    const abort = new AbortController();
    activeAbort.current = abort;

    try {
      for await (const event of transport.send(payload, abort.signal)) {
        consumeEvent(event);
      }
      if (stateRef.current.phase !== "error") {
        dispatch({ type: "run/phase", phase: "idle" });
        dispatch({ type: "message/set-active-assistant", messageId: null });
      }
      return true;
    } catch (error) {
      if (abort.signal.aborted) {
        dispatch({ type: "run/phase", phase: "idle" });
        return false;
      }
      dispatch({
        type: "run/error",
        message: error instanceof Error ? error.message : String(error),
      });
      return false;
    } finally {
      activeAbort.current = null;
    }
  }, [consumeEvent, dispatch, transport]);

  // Drain exactly one queued follow-up after a turn settles. Keeping this in an
  // effect makes the dependency on the committed phase explicit and avoids
  // microtask races between React updates and transport completion.
  useEffect(() => {
    if (state.phase !== "idle" || state.queue.length === 0 || activeAbort.current) return;
    const next = state.queue[0]!;
    dispatch({ type: "queue/dequeue-head" });
    void runPayload({
      conversationId: state.conversationId,
      messageId: next.id,
      text: next.text,
      attachments: next.attachments,
      mode: "queued",
    }, true);
  }, [dispatch, runPayload, state.conversationId, state.phase, state.queue]);

  const setDraft = useCallback((text: string) => {
    dispatch({ type: "draft/set-text", text });
  }, [dispatch]);

  const cancelEditing = useCallback(() => {
    dispatch({ type: "draft/cancel-edit" });
  }, [dispatch]);

  const dismissError = useCallback(() => {
    dispatch({ type: "run/clear-error" });
  }, [dispatch]);

  const submit = useCallback(async (mode: "auto" | BusySubmitMode = "auto") => {
    const current = stateRef.current;
    const text = current.draft.text.trim();
    if (!text && current.draft.attachments.length === 0) return false;

    if (/^\/btw(?:\s|$)/i.test(text)) {
      const sideText = text.replace(/^\/btw(?:\s|$)/i, "").trim();
      dispatch({ type: "draft/clear" });
      dispatch({ type: "side-chat", action: { type: "open" } });
      if (sideText) return sendSideChat(sideText);
      return true;
    }

    if (current.draft.editingMessageId) {
      const original = findMessage(current, current.draft.editingMessageId);
      if (original?.role === "user") {
        dispatch({
          type: "message/replace",
          message: { ...original, text, attachments: current.draft.attachments },
        });
        dispatch({ type: "message/remove-after", messageId: original.id });
        dispatch({ type: "draft/clear" });
        return runPayload({
          conversationId: current.conversationId,
          messageId: original.id,
          text,
          attachments: current.draft.attachments,
          mode: "edit-retry",
        }, false);
      }
    }

    const busy = current.phase === "sending" || current.phase === "responding" || current.phase === "stopping";
    const messageId = uid("user");

    if (busy) {
      if (mode === "steer" && transport.steer) {
        const user: UserMessage = {
          id: messageId,
          role: "user",
          text,
          attachments: current.draft.attachments,
          timestamp: Date.now(),
          deliveryStatus: "sent",
          awaitingPickup: true,
          steerReceipt: "unread",
        };
        dispatch({ type: "message/append", message: user });
        dispatch({ type: "draft/clear" });
        const accepted = await transport.steer({
          conversationId: current.conversationId,
          messageId,
          text,
          attachments: current.draft.attachments,
          mode: "steer",
        });
        if (!accepted) {
          dispatch({ type: "message/remove", messageId });
          dispatch({ type: "draft/set", draft: { ...current.draft, text } });
          return false;
        }
        return true;
      }

      if (current.queue.length >= FRONTEND_QUEUE_CAP) return false;
      dispatch({
        type: "queue/enqueue",
        item: createQueuedDraft({
          id: messageId,
          text,
          attachments: current.draft.attachments,
          conversationId: current.conversationId,
          busy: true,
          existingDepth: current.queue.length,
        }),
      });
      dispatch({ type: "draft/clear" });
      return true;
    }

    dispatch({ type: "draft/clear" });
    return runPayload({
      conversationId: current.conversationId,
      messageId,
      text,
      attachments: current.draft.attachments,
      mode: "normal",
    }, true);
  // sendSideChat is defined below but stable through ref-like React closure semantics.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runPayload, transport]);

  const stop = useCallback(async () => {
    const current = stateRef.current;
    if (current.phase !== "sending" && current.phase !== "responding") return;
    dispatch({ type: "run/phase", phase: "stopping" });
    // Important: observed Claude queue behavior restores queued input when stopping.
    if (current.queue.length > 0) dispatch({ type: "queue/restore-to-draft" });
    try {
      await transport.stop?.(current.conversationId);
    } finally {
      activeAbort.current?.abort();
      activeAbort.current = null;
      dispatch({ type: "run/phase", phase: "idle" });
      dispatch({ type: "message/set-active-assistant", messageId: null });
    }
  }, [transport]);

  const removeQueued = useCallback((id: string) => dispatch({ type: "queue/remove", id }), []);
  const editQueued = useCallback((id: string, text: string) => dispatch({ type: "queue/edit", id, text }), []);
  const reorderQueued = useCallback((activeId: string, overId: string) => dispatch({ type: "queue/reorder", activeId, overId }), []);
  const clearQueue = useCallback(() => dispatch({ type: "queue/clear" }), []);

  const sendQueuedNow = useCallback(async (id: string) => {
    const current = stateRef.current;
    const item = current.queue.find(candidate => candidate.id === id);
    if (!item) return false;
    if (current.phase === "idle") {
      dispatch({ type: "queue/remove", id });
      return runPayload({
        conversationId: current.conversationId,
        messageId: item.id,
        text: item.text,
        attachments: item.attachments,
        mode: "queued",
      }, true);
    }
    if (!transport.steer) return false;
    dispatch({ type: "queue/remove", id });
    const user: UserMessage = {
      id: item.id,
      role: "user",
      text: item.text,
      attachments: item.attachments,
      timestamp: Date.now(),
      deliveryStatus: "sent",
      awaitingPickup: true,
      steerReceipt: "unread",
    };
    dispatch({ type: "message/append", message: user });
    const accepted = await transport.steer({
      conversationId: current.conversationId,
      messageId: item.id,
      text: item.text,
      attachments: item.attachments,
      mode: "steer",
    });
    if (!accepted) {
      dispatch({ type: "message/remove", messageId: item.id });
      dispatch({ type: "queue/enqueue", item });
    }
    return Boolean(accepted);
  }, [runPayload, transport]);

  const interruptSteer = useCallback(async (messageId: string) => {
    const current = stateRef.current;
    if (!transport.interruptForSteer) return false;
    const ok = await transport.interruptForSteer(current.conversationId, messageId);
    if (ok) markSteerRead(messageId);
    return Boolean(ok);
  }, [markSteerRead, transport]);

  const cancelAndEditSteer = useCallback(async (messageId: string) => {
    const current = stateRef.current;
    const message = findMessage(current, messageId);
    if (message?.role !== "user") return false;
    const ok = await transport.cancelSteer?.(current.conversationId, messageId);
    if (ok === false) return false;
    dispatch({ type: "message/remove", messageId });
    dispatch({ type: "draft/set", draft: { text: message.text, attachments: message.attachments ?? [], editingMessageId: null } });
    return true;
  }, [transport]);

  const editAndRetry = useCallback((messageId: string) => {
    const message = findMessage(stateRef.current, messageId);
    if (message?.role !== "user") return;
    dispatch({ type: "draft/edit-message", messageId, text: message.text, attachments: message.attachments ?? [] });
  }, []);

  const retryAssistant = useCallback(async (messageId: string) => {
    const current = stateRef.current;
    if (current.phase !== "idle" && current.phase !== "error") return false;
    const user = findUserBefore(current, messageId);
    if (!user) return false;
    dispatch({ type: "message/remove-after", messageId: user.id });
    return runPayload({
      conversationId: current.conversationId,
      messageId: user.id,
      text: user.text,
      attachments: user.attachments ?? [],
      mode: "retry",
    }, false);
  }, [runPayload]);

  const forkFrom = useCallback(async (messageId: string) => {
    const current = stateRef.current;
    if (!transport.fork) return null;
    const forkId = await transport.fork(current.conversationId, messageId);
    onForkCreated?.(forkId, messageId);
    return forkId;
  }, [onForkCreated, transport]);

  const rewindTo = useCallback(async (messageId: string) => {
    const current = stateRef.current;
    if (current.phase === "responding" || current.phase === "sending") return false;
    if (transport.rewind) {
      const accepted = await transport.rewind(current.conversationId, messageId);
      if (!accepted) return false;
    }
    dispatch({ type: "message/remove-after", messageId });
    return true;
  }, [transport]);

  const toggleSideChat = useCallback((force?: boolean) => {
    const open = force ?? !stateRef.current.sideChat.open;
    dispatch({ type: "side-chat", action: { type: open ? "open" : "close" } });
  }, []);

  const clearSideChat = useCallback(() => {
    dispatch({ type: "side-chat", action: { type: "clear" } });
  }, []);

  const sendSideChat = useCallback(async (text: string) => {
    let nextText: string | null = text.trim();
    if (!nextText || !transport.sideChatSend) return false;

    // A follow-up entered while the side chat is busy is held once and consumed
    // after the current side turn ends. This mirrors the observed per-session
    // queued side-chat behavior without contaminating the main transcript.
    if (stateRef.current.sideChat.status === "thinking") {
      dispatch({ type: "side-chat", action: { type: "send", text: nextText, id: uid("side-user"), timestamp: Date.now() } });
      return true;
    }

    while (nextText) {
      const current = stateRef.current;
      const userId = uid("side-user");
      const assistantId = uid("side-assistant");
      dispatch({ type: "side-chat", action: { type: "send", text: nextText, id: userId, timestamp: Date.now() } });

      const abort = new AbortController();
      sideAbort.current = abort;
      let failed = false;
      try {
        for await (const event of transport.sideChatSend(current.conversationId, nextText, abort.signal)) {
          if (event.type === "delta") {
            dispatch({ type: "side-chat", action: { type: "assistant-delta", text: event.text, id: assistantId, timestamp: Date.now() } });
          } else if (event.type === "tool") {
            dispatch({ type: "side-chat", action: { type: "tool", label: event.label } });
          } else if (event.type === "error") {
            failed = true;
            dispatch({ type: "side-chat", action: { type: "error", message: event.message } });
          }
        }
      } catch (error) {
        if (!abort.signal.aborted) {
          failed = true;
          dispatch({ type: "side-chat", action: { type: "error", message: error instanceof Error ? error.message : String(error) } });
        }
      } finally {
        sideAbort.current = null;
      }

      if (failed) return false;
      const queued = stateRef.current.sideChat.queued;
      dispatch({ type: "side-chat", action: { type: "turn-end" } });
      if (queued) dispatch({ type: "side-chat", action: { type: "consume-queued" } });
      nextText = queued;
    }
    return true;
  }, [dispatch, transport]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === ";") {
        event.preventDefault();
        toggleSideChat();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleSideChat]);

  const value = useMemo<ConversationController>(() => ({
    state,
    capabilities: {
      steering: Boolean(transport.steer),
      interrupt: Boolean(transport.interruptForSteer),
      fork: Boolean(transport.fork),
      rewind: Boolean(transport.rewind),
      sideChat: Boolean(transport.sideChatSend),
    },
    setDraft,
    cancelEditing,
    dismissError,
    submit,
    stop,
    removeQueued,
    editQueued,
    reorderQueued,
    clearQueue,
    sendQueuedNow,
    interruptSteer,
    cancelAndEditSteer,
    editAndRetry,
    retryAssistant,
    forkFrom,
    rewindTo,
    toggleSideChat,
    clearSideChat,
    sendSideChat,
  }), [
    state,
    transport,
    setDraft,
    cancelEditing,
    dismissError,
    submit,
    stop,
    removeQueued,
    editQueued,
    reorderQueued,
    clearQueue,
    sendQueuedNow,
    interruptSteer,
    cancelAndEditSteer,
    editAndRetry,
    retryAssistant,
    forkFrom,
    rewindTo,
    toggleSideChat,
    clearSideChat,
    sendSideChat,
  ]);

  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>;
}

export function useConversation(): ConversationController {
  const value = useContext(ConversationContext);
  if (!value) throw new Error("useConversation must be used inside ConversationProvider");
  return value;
}
