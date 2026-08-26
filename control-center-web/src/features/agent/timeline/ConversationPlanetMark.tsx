export type ConversationPlanetState =
  | 'idle'
  | 'thinking'
  | 'running'
  | 'waiting'
  | 'done'
  | 'failed';

/* One stable DOM tree covers every state. The outer ring is visually hidden
   when work settles, but it is never mounted/unmounted during live updates;
   this prevents streaming rerenders from restarting the indicator or making
   it blink. Motion remains a state signal, not decoration. */
const liveStates = new Set<ConversationPlanetState>(['thinking', 'running', 'waiting']);

export function ConversationPlanetMark({
  label,
  size = 'md',
  state,
}: {
  /** Present only where the mark is the sole carrier of the state; otherwise the
   *  adjacent text already names it and the mark stays decorative. */
  label?: string;
  size?: 'sm' | 'md' | 'lg';
  state: ConversationPlanetState;
}) {
  const live = liveStates.has(state);
  return (
    <span
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className="paw-conv-planet"
      data-live={live ? 'true' : undefined}
      data-size={size}
      data-state={state}
      role={label ? 'img' : undefined}
    >
      <span className="paw-conv-planet__body" />
      <span className="paw-conv-planet__orbit" />
    </span>
  );
}
