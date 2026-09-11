import { useEffect, useRef } from 'react';
import ringedPlanet from '../assets/stellar/planet-cinematic.png';
import type { StellarPlanetRenderer } from './stellar-planet-renderer';

export function PawStellarPlanet() {
  const planetRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const planet = planetRef.current;
    const image = imageRef.current;
    const canvas = canvasRef.current;
    const scene = planet?.closest<HTMLElement>('.paw-stellar-scene');
    if (!planet || !image || !canvas || !scene || !window.WebGLRenderingContext) return;
    let renderer: StellarPlanetRenderer | null = null;
    let closed = false;
    let loading = false;
    let unavailable = false;
    const reconcile = () => {
      const paused = scene.dataset.stellarPaused !== 'false';
      if (renderer) { renderer.setPaused(paused); return; }
      if (closed || paused || loading || unavailable || !image.complete || !image.naturalWidth) return;
      loading = true;
      void import('./stellar-planet-renderer').then(({ createStellarPlanetRenderer }) => {
        if (closed) return;
        // An App can open while the material chunk is loading.
        if (scene.dataset.stellarPaused !== 'false') return;
        renderer = createStellarPlanetRenderer(canvas, image, () => {
          unavailable = true;
          delete planet.dataset.materialReady;
        });
        if (!renderer) { unavailable = true; return; }
        planet.dataset.materialReady = 'true';
        renderer.setPaused(false);
      }).catch(() => { unavailable = true; }).finally(() => {
        loading = false;
        if (!closed) reconcile();
      });
    };
    const observer = new MutationObserver(reconcile);
    observer.observe(scene, { attributes: true, attributeFilter: ['data-stellar-paused'] });
    const resize = new ResizeObserver(() => renderer?.resize());
    resize.observe(planet);
    image.addEventListener('load', reconcile);
    reconcile();
    return () => {
      closed = true;
      observer.disconnect();
      resize.disconnect();
      image.removeEventListener('load', reconcile);
      renderer?.dispose();
      delete planet.dataset.materialReady;
    };
  }, []);

  return (
    <div className="paw-stellar-scene__planet" ref={planetRef}>
      <img alt="" className="paw-stellar-scene__planet-image" decoding="async" draggable={false} ref={imageRef} src={ringedPlanet} />
      <canvas aria-hidden="true" className="paw-stellar-scene__planet-material" ref={canvasRef} />
    </div>
  );
}
