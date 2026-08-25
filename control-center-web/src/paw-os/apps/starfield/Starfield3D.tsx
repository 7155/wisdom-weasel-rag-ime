/**
 * React wrapper around the WebGL starfield stage.
 *
 * - three.js is loaded lazily so the main bundle never pays for the sky;
 * - every celestial body also exists as a real DOM button in the label
 *   layer (keyboard and screen-reader access), positioned by the stage,
 *   carrying the real work it is running so the sky reads as work first;
 * - a handoff in flight also gets a label at its beam midpoint, so a live
 *   beam says which WorkItem is moving instead of just glowing;
 * - the render loop only runs while the host is actually on screen: the
 *   `running` prop (page visible + sky watched) is combined with an
 *   IntersectionObserver so a scrolled-away or covered sky costs zero rAF;
 * - WebGL setup failure or context loss reports through `onFallback` so the
 *   host can swap in the fullscreen 2D sky without losing any state.
 */

import { useEffect, useRef, useState } from 'react';
import type { StarfieldStage } from './starfield-scene';
import {
  liveBeamLinks,
  sceneBodyAriaLabel,
  type StarfieldSceneModel,
} from './starfield-scene-model';

export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

/** System preference or the PAWOS-level `:root[data-reduce-motion]` switch. */
function motionCurrentlyReduced(): boolean {
  if (document.documentElement.getAttribute('data-reduce-motion') === 'true') return true;
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(motionCurrentlyReduced);
  useEffect(() => {
    const update = () => setReduced(motionCurrentlyReduced());
    const media = typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)')
      : null;
    media?.addEventListener('change', update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-reduce-motion'],
    });
    return () => {
      media?.removeEventListener('change', update);
      observer.disconnect();
    };
  }, []);
  return reduced;
}

export function Starfield3D({
  model,
  running,
  selectedId,
  onPick,
  onFallback,
}: {
  model: StarfieldSceneModel;
  /** Page visible and sky watched: only then does the render loop run. */
  running: boolean;
  selectedId: string | null;
  onPick: (bodyId: string | null) => void;
  onFallback: () => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const labelsRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<StarfieldStage | null>(null);
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;
  const onFallbackRef = useRef(onFallback);
  onFallbackRef.current = onFallback;
  const [stageReady, setStageReady] = useState(0);
  const [inView, setInView] = useState(true);
  const reducedMotion = useReducedMotion();

  // Deepened pause: a sky scrolled out of the viewport stops its loop even
  // while the page itself stays visible.
  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof IntersectionObserver !== 'function') return undefined;
    const observer = new IntersectionObserver((entries) => {
      setInView(entries[entries.length - 1]?.isIntersecting ?? true);
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    const labelLayer = labelsRef.current;
    if (!host || !canvas || !labelLayer) return undefined;
    let disposed = false;
    let stage: StarfieldStage | null = null;
    let observer: ResizeObserver | null = null;
    void (async () => {
      try {
        const { StarfieldStage: Stage } = await import('./starfield-scene');
        if (disposed) return;
        stage = new Stage({
          canvas,
          labelLayer,
          onPick: (bodyId) => onPickRef.current(bodyId),
          onContextLost: () => onFallbackRef.current(),
        });
        stageRef.current = stage;
        stage.resize(host.clientWidth, host.clientHeight);
        observer = new ResizeObserver(() => {
          stage?.resize(host.clientWidth, host.clientHeight);
        });
        observer.observe(host);
        setStageReady((value) => value + 1);
      } catch {
        if (!disposed) onFallbackRef.current();
      }
    })();
    return () => {
      disposed = true;
      observer?.disconnect();
      stage?.dispose();
      stageRef.current = null;
    };
  }, []);

  useEffect(() => {
    stageRef.current?.setModel(model);
  }, [model, stageReady]);
  useEffect(() => {
    stageRef.current?.setReducedMotion(reducedMotion);
  }, [reducedMotion, stageReady]);
  useEffect(() => {
    stageRef.current?.setSelected(selectedId);
  }, [selectedId, stageReady]);
  useEffect(() => {
    stageRef.current?.setRunning(running && inView);
  }, [running, inView, stageReady]);

  return (
    <div className="paw-sf__stage3d" ref={hostRef}>
      <canvas aria-hidden="true" className="paw-sf__canvas" ref={canvasRef} />
      <div aria-hidden="true" className="paw-sf__vignette" />
      <div className="paw-sf__labels" ref={labelsRef}>
        {model.center ? (
          <button
            aria-label={`${model.center.title} · ${model.center.subtitle}`}
            className="paw-sf-label paw-sf-label--center"
            data-sf-body="center"
            data-selected={selectedId === 'center' || undefined}
            data-tone={model.center.motion.tone}
            data-working={model.center.motion.working || undefined}
            key="center"
            onClick={() => onPick('center')}
            type="button"
          >
            <strong>{model.center.title}</strong>
            <small>{model.center.subtitle}</small>
          </button>
        ) : null}
        {model.bodies.map((body) => (
          <button
            aria-label={sceneBodyAriaLabel(model.mode, body)}
            className="paw-sf-label"
            data-idle={body.idle || undefined}
            data-sf-body={body.id}
            data-selected={selectedId === body.id || undefined}
            data-tone={body.motion.tone}
            data-working={body.motion.working || undefined}
            key={body.id}
            onClick={() => onPick(body.id)}
            title={body.detail || undefined}
            type="button"
          >
            <strong>{body.title}</strong>
            <small>{body.subtitle}</small>
            {body.task && !body.idle ? <em>{body.task}</em> : null}
          </button>
        ))}
        {liveBeamLinks(model).map((link) => (
          <span className="paw-sf-beam-label" data-sf-link={link.id} key={link.id}>
            {link.label}
          </span>
        ))}
      </div>
    </div>
  );
}
