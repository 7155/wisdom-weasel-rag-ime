import { useEffect, useRef, useState } from 'react';
import type { ProjectGalaxyStage } from './project-galaxy-stage';
import type { ProjectGalaxyModel } from './project-galaxy-model';

/** Lazy WebGL ownership and accessible labels over the exact same real IDs. */
export function PawProjectGalaxyScene({ model, running, speed = 1, selectedId, onPick, onFallback }: {
  model: ProjectGalaxyModel; running: boolean; speed?: number; selectedId: string | null;
  onPick(id: string | null): void; onFallback(): void;
}) {
  const host = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null), labels = useRef<HTMLDivElement>(null);
  const stage = useRef<ProjectGalaxyStage | null>(null);
  const pick = useRef(onPick), fallback = useRef(onFallback);
  pick.current = onPick; fallback.current = onFallback;
  const [ready, setReady] = useState(false);
  const [inView, setInView] = useState(true);
  const [reduced, setReduced] = useState(() => document.documentElement.dataset.reduceMotion === 'true' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true);
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(document.documentElement.dataset.reduceMotion === 'true' || media?.matches === true);
    media?.addEventListener('change', update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduce-motion'] });
    return () => { media?.removeEventListener('change', update); observer.disconnect(); };
  }, []);
  useEffect(() => {
    let disposed = false;
    let resize: ResizeObserver | undefined;
    let intersection: IntersectionObserver | undefined;
    void import('./project-galaxy-stage').then(({ ProjectGalaxyStage: Stage }) => {
      if (disposed || !host.current || !canvas.current || !labels.current) return;
      try {
        stage.current = new Stage({ canvas: canvas.current, labels: labels.current, seed: model.seed,
          onPick: (id) => pick.current(id), onLost: () => fallback.current() });
        const fit = () => { if (host.current) stage.current?.resize(host.current.clientWidth, host.current.clientHeight); };
        resize = new ResizeObserver(fit); resize.observe(host.current); fit();
        if (typeof IntersectionObserver === 'function') {
          intersection = new IntersectionObserver((entries) => setInView(entries[entries.length - 1]?.isIntersecting ?? true));
          intersection.observe(host.current);
        }
        setReady(true);
      } catch { stage.current?.dispose(); stage.current = null; fallback.current(); }
    }).catch(() => { if (!disposed) fallback.current(); });
    return () => { disposed = true; resize?.disconnect(); intersection?.disconnect(); stage.current?.dispose(); stage.current = null; };
  }, [model.seed]);
  useEffect(() => { if (ready) stage.current?.setModel(model); }, [model, ready]);
  useEffect(() => { stage.current?.setSelected(selectedId); }, [selectedId, ready]);
  useEffect(() => { stage.current?.setMotion(running && inView, reduced, speed); }, [running, inView, reduced, speed, ready]);
  return <div className="paw-project-universe" data-ready={ready} data-motion={reduced ? 'reduced' : running && inView && speed > 0 ? 'active' : 'paused'} ref={host}>
    <canvas aria-hidden="true" data-galaxy-renderer="webgl" ref={canvas} />
    {!ready ? <p className="paw-project-universe__loading" role="status">正在展开星系…</p> : null}
    <div className="paw-project-universe__labels" ref={labels}>
      <svg aria-hidden="true" className="paw-project-universe__leaders"><line data-galaxy-leader="center" />{model.bodies.map((body) => <line data-galaxy-leader={body.id} key={body.id} />)}</svg>
      <button aria-label={`${model.center.title} · 项目文档`} aria-pressed={selectedId === 'center'} className="paw-project-universe__label paw-project-universe__label--core" data-galaxy-body="center" onClick={() => onPick('center')} type="button"><strong>项目文档</strong></button>
      {model.bodies.map((body) => <button aria-label={`${body.title}，${body.subtitle}`} aria-pressed={selectedId === body.id}
        className="paw-project-universe__label" data-galaxy-body={body.id} data-running={body.motion.working} data-tone={body.motion.tone}
        key={body.id} onClick={() => onPick(body.id)} title={body.detail || undefined} type="button">
        <strong>{body.title}</strong><small>{body.subtitle}</small>
      </button>)}
    </div>
  </div>;
}
