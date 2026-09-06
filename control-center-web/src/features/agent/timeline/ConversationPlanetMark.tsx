import { useEffect, useRef, useState } from 'react';

export type ConversationPlanetState =
  | 'idle'
  | 'thinking'
  | 'running'
  | 'waiting'
  | 'done'
  | 'failed';

/* One stable nucleus/orbit tree covers every state. Only authoritative live
   thinking and execution rotate; waiting and settled receipts stay still. */
const liveStates = new Set<ConversationPlanetState>(['thinking', 'running']);

export function ConversationPlanetMark({
  label,
  motionActive,
  size = 'md',
  state,
}: {
  /** Present only where the mark is the sole carrier of the state; otherwise the
   *  adjacent text already names it and the mark stays decorative. */
  label?: string;
  /** Parent surfaces can pause a collapsed or otherwise inactive group. */
  motionActive?: boolean;
  size?: 'sm' | 'md' | 'lg';
  state: ConversationPlanetState;
}) {
  const live = liveStates.has(state);
  const rootRef = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    // Activity stacks already observe their surface once. Standalone marks
    // own visibility only while live, so history adds no observers/listeners.
    if (!live || motionActive !== undefined) return;
    let intersecting = true;
    const update = () => setVisible(!document.hidden && intersecting);
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver((entries) => {
      intersecting = entries.some((entry) => entry.isIntersecting);
      update();
    });
    if (rootRef.current) observer?.observe(rootRef.current);
    document.addEventListener('visibilitychange', update);
    update();
    return () => {
      observer?.disconnect();
      document.removeEventListener('visibilitychange', update);
    };
  }, [live, motionActive]);
  return (
    <span
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className="paw-conv-planet"
      data-live={live ? 'true' : undefined}
      data-motion={live && (motionActive ?? visible) ? 'active' : 'paused'}
      data-size={size}
      data-state={state}
      ref={rootRef}
      role={label ? 'img' : undefined}
    >
      <span className="paw-conv-planet__body" />
      <svg aria-hidden="true" className="paw-conv-planet__orbit" viewBox="0 0 32 32" fill="none">
        <g className="paw-conv-planet__spiral" stroke="currentColor" strokeLinecap="round">
          <path d="M16 10C24 8 29 14 26 21C23 28 10 29 5 21" opacity=".35" />
          <path d="M16 22C8 24 3 18 6 11C9 4 22 3 27 11" opacity=".35" />
          <path d="M16 10C22 9 25 12 25 16M16 22C10 23 7 20 7 16" strokeWidth="1.6" />
          <circle cx="25" cy="16" r="1.5" fill="currentColor" stroke="none" />
          <circle cx="7" cy="16" r="1" fill="currentColor" stroke="none" />
        </g>
        <g className="paw-conv-planet__satellites" stroke="currentColor">
          <circle cx="16" cy="16" r="11" opacity=".28" />
          <path d="M16 5A11 11 0 0 1 27 16" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="27" cy="16" r="2" fill="currentColor" stroke="none" />
          <circle cx="5" cy="16" r="1.2" fill="currentColor" stroke="none" opacity=".65" />
        </g>
      </svg>
    </span>
  );
}
