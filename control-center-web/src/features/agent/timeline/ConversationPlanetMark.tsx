export type ConversationPlanetState =
  | 'idle'
  | 'thinking'
  | 'running'
  | 'waiting'
  | 'done'
  | 'failed';

/* The vendored conversation surface marks live work with a single pulsing dot
   (`ccui-thinking-dot`, `ccui-tool-status`). PAWOS keeps that rhythm but gives
   the dot a body: a lit sphere, and — only while the state is actually live —
   an orbit carrying one moon. A settled state keeps the sphere and drops the
   orbit, so motion in the transcript always means the Runtime is still working. */
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
      {live ? <span className="paw-conv-planet__orbit" /> : null}
    </span>
  );
}
