import { type CSSProperties, useEffect, useMemo, useRef } from 'react';
import { useMotionValueEvent, useSpring } from 'motion/react';
import nebula from '../assets/stellar/nebula.png';
import { PawStopMotionPlanet } from './PawStopMotionPlanet';
import { usePawWorkDirectory } from './PawWorkDirectory';
import { projectStellarAgents, type StellarAgentProjection } from './stellar-agent-projection';
import { StellarAgentField } from './StellarAgentField';
import { createStellarStopMotion } from './stellar-stop-motion';

const spring = { mass: 1, stiffness: 100, damping: 10 };
// A fixed sky avoids hydration changes and never implies Runtime activity.
const scatter = (index: number, salt: number) => {
  const value = Math.sin(index * 127.1 + salt * 311.7) * 43758.5453;
  return value - Math.floor(value);
};
const stars = Array.from({ length: 96 }, (_, index) => ({
  left: `${scatter(index, 1) * 100}%`,
  top: `${scatter(index, 2) * 100}%`,
  width: index % 13 === 0 ? 3 : index % 3 === 0 ? 2 : 1,
  height: index % 13 === 0 ? 3 : index % 3 === 0 ? 2 : 1,
  opacity: .35 + (index % 4) * .15,
  '--star-delay': `${-scatter(index, 3) * 19}s`,
  '--star-duration': `${11 + scatter(index, 4) * 8}s`,
}));
const dust = Array.from({ length: 64 }, (_, index) => ({
  left: `${scatter(index, 5) * 100}%`,
  top: `${scatter(index, 6) * 100}%`,
  opacity: .18 + scatter(index, 7) * .4,
}));

/** A painted sky with independently moving depth planes. Reading, window
 * gestures and accessibility preferences share the desktop's suspension
 * contract. Pointer input changes two spring values, never React state. */
export function PawStellarBackdrop({ agents }: { agents?: StellarAgentProjection } = {}) {
  const sceneRef = useRef<HTMLDivElement>(null);
  const farRef = useRef<HTMLDivElement>(null);
  const middleRef = useRef<HTMLDivElement>(null);
  const planetRef = useRef<HTMLDivElement>(null);
  const nearRef = useRef<HTMLDivElement>(null);
  const x = useSpring(0, spring);
  const y = useSpring(0, spring);
  const paintDepth = () => {
    for (const [element, depth] of [[farRef.current, 6], [middleRef.current, 12], [planetRef.current, 28], [nearRef.current, 20]] as const) {
      if (element) element.style.transform = `translate3d(${x.get() * depth}px, ${y.get() * depth}px, 0)`;
    }
  };
  useMotionValueEvent(x, 'change', paintDepth);
  useMotionValueEvent(y, 'change', paintDepth);

  useEffect(() => {
    const scene = sceneRef.current;
    const desktop = scene?.closest<HTMLElement>('.paw-desktop');
    const root = scene?.closest<HTMLElement>('.paw-desktop-root');
    if (!scene || !desktop || !root) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const pointer = window.matchMedia('(hover: hover) and (pointer: fine)');
    const sky = scene.querySelector<HTMLImageElement>('.paw-stellar-scene__nebula');
    const stopMotion = sky ? createStellarStopMotion(sky) : undefined;
    let enabled = false;
    const reconcile = () => {
      enabled = root.dataset.pawVisual === 'stellar'
        && !document.hidden && !reduced.matches && pointer.matches
        && document.documentElement.dataset.reduceMotion !== 'true'
        && document.documentElement.dataset.pawProjectGalaxy !== 'open'
        && !root.dataset.windowInteraction
        && !desktop.hasAttribute('data-ambient-paused')
        && !desktop.hasAttribute('data-collaboration-focus')
        && !desktop.hasAttribute('data-overview');
      scene.dataset.stellarPaused = String(!enabled);
      stopMotion?.setEnabled(enabled);
      if (!enabled) { x.jump(0); y.jump(0); }
    };
    const move = (event: PointerEvent) => {
      if (!enabled || event.pointerType === 'touch' || event.buttons !== 0) return;
      const rect = desktop.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      x.set(Math.max(-1, Math.min(1, (event.clientX - rect.left) / rect.width * 2 - 1)));
      y.set(Math.max(-1, Math.min(1, (event.clientY - rect.top) / rect.height * 2 - 1)));
    };
    const rest = () => { if (enabled) { x.set(0); y.set(0); } };
    const observer = new MutationObserver(reconcile);
    observer.observe(root, { attributes: true, attributeFilter: ['data-paw-visual', 'data-window-interaction'] });
    observer.observe(desktop, { attributes: true, attributeFilter: ['data-ambient-paused', 'data-collaboration-focus', 'data-overview'] });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduce-motion', 'data-paw-project-galaxy'] });
    reduced.addEventListener?.('change', reconcile);
    pointer.addEventListener?.('change', reconcile);
    document.addEventListener('visibilitychange', reconcile);
    desktop.addEventListener('pointermove', move, { passive: true });
    desktop.addEventListener('pointerleave', rest);
    reconcile();
    return () => {
      stopMotion?.dispose();
      observer.disconnect();
      reduced.removeEventListener?.('change', reconcile);
      pointer.removeEventListener?.('change', reconcile);
      document.removeEventListener('visibilitychange', reconcile);
      desktop.removeEventListener('pointermove', move);
      desktop.removeEventListener('pointerleave', rest);
      x.jump(0); y.jump(0);
    };
  }, [x, y]);

  return (
    <div aria-hidden="true" className="paw-stellar-scene" data-agent-count={agents?.runningPlanets.length ?? 0} data-stellar-paused="true" ref={sceneRef}>
      <div className="paw-stellar-scene__far" ref={farRef}>
        <div className="paw-stellar-scene__clouds">
          <img alt="" className="paw-stellar-scene__nebula" decoding="async" draggable={false} src={nebula} />
        </div>
        <div className="paw-stellar-scene__dust">{dust.map((style, index) => <i key={index} style={style} />)}</div>
      </div>
      <div className="paw-stellar-scene__daylight" />
      <div className="paw-stellar-scene__middle" ref={middleRef}>
        <div className="paw-stellar-scene__moon"><div className="paw-stellar-scene__moon-clouds" style={{ backgroundImage: `url(${import.meta.env.BASE_URL}paw-media/starfield/moon-512.jpg)` }} /></div>
        <div className="paw-stellar-scene__distant-world" />
        <div className="paw-stellar-scene__light-wisp" />
      </div>
      <div className="paw-stellar-scene__planet-plane" ref={planetRef}>
        <PawStopMotionPlanet />
        {agents ? <StellarAgentField projection={agents} /> : null}
      </div>
      <div className="paw-stellar-scene__near" ref={nearRef}>
        <div className="paw-stellar-scene__stars">
          {stars.map((style, index) => <i data-bright-sky={parseFloat(style.left) < 58 || undefined} key={index} style={style as CSSProperties} />)}
        </div>
        <div className="paw-stellar-scene__meteor" />
      </div>
    </div>
  );
}

/** Share the shell's existing directory. The wallpaper never starts Sessions,
 * polls its own Runtime or infers activity from the number of open windows. */
export function PawStellarWallpaper() {
  const { sessions, rooms, sessionStatusFresh, roomStatusFresh } = usePawWorkDirectory();
  const agents = useMemo(() => projectStellarAgents({
    nowMs: Date.now(), sessions, rooms, sessionStatusFresh, roomStatusFresh,
  }), [sessions, rooms, sessionStatusFresh, roomStatusFresh]);
  return <PawStellarBackdrop agents={agents} />;
}
