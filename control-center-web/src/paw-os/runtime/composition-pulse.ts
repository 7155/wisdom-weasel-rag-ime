export const PAW_COMPOSITION_PULSE_EVENT = 'pawos:composition-pulse';

export type PawCompositionPulseSource = 'app' | 'system' | 'music' | 'agent' | 'room';

export function pulsePawComposition(source: PawCompositionPulseSource, energy = .65): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(PAW_COMPOSITION_PULSE_EVENT, { detail: { energy, source } }));
}

const agentPulseEvents = new Set([
  'reasoning_summary', 'message_completed', 'tool_started', 'tool_finished',
  'approval_required', 'user_input_required', 'turn_completed', 'turn_failed',
]);
const roomPulseEvents = new Set([
  'route_decision', 'participant_activity', 'participant_message', 'room_post',
  'turn_completed', 'turn_failed',
]);

export function pulsePawCompositionForRuntimeEvent(source: 'agent' | 'room', eventType: string): void {
  const events = source === 'agent' ? agentPulseEvents : roomPulseEvents;
  if (!events.has(eventType)) return;
  pulsePawComposition(source, eventType === 'turn_completed' || eventType === 'turn_failed' ? .82 : .56);
}

export function pulsePawCompositionForRuntimeEvents(source: 'agent' | 'room', eventTypes: readonly string[]): void {
  const events = source === 'agent' ? agentPulseEvents : roomPulseEvents;
  const eventType = [...eventTypes].reverse().find((type) => events.has(type));
  if (eventType) pulsePawCompositionForRuntimeEvent(source, eventType);
}
