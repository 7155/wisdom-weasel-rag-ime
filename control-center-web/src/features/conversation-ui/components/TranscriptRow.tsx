import type { TranscriptMessage } from '../model/types';
import { AssistantTurn } from './AssistantTurn';
import { UserTurn } from './UserTurn';

export function TranscriptRow({ message }: { message: TranscriptMessage }) {
  return message.role === 'user' ? <UserTurn message={message} /> : <AssistantTurn message={message} />;
}
