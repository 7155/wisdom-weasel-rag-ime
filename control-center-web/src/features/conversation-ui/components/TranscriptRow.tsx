import React from "react";
import type { TranscriptMessage } from "../model/types";
import { UserTurn } from "./UserTurn";
import { AssistantTurn } from "./AssistantTurn";

export function TranscriptRow({ message }: { message: TranscriptMessage }) {
  return message.role === "user" ? <UserTurn message={message} /> : <AssistantTurn message={message} />;
}
