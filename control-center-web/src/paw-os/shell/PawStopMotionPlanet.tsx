import { useEffect, useRef } from 'react';
import { createStellarStopMotion } from './stellar-stop-motion';

const frames = Object.entries(import.meta.glob<string>(
  '../assets/stellar/ringed-frames/*.png', { eager: true, query: '?url', import: 'default' },
)).sort(([a], [b]) => a.localeCompare(b)).map(([, url]) => url);

export function PawStopMotionPlanet() {
  const imageRef = useRef<HTMLImageElement>(null);
  useEffect(() => {
    const image = imageRef.current;
    const scene = image?.closest<HTMLElement>('.paw-stellar-scene');
    if (!image || !scene) return;
    const player = createStellarStopMotion(image, frames, 2000);
    const reconcile = () => player.setEnabled(scene.dataset.stellarPaused === 'false');
    const observer = new MutationObserver(reconcile);
    observer.observe(scene, { attributes: true, attributeFilter: ['data-stellar-paused'] });
    reconcile();
    return () => { observer.disconnect(); player.dispose(); };
  }, []);
  return <div className="paw-stellar-scene__planet" style={{ animation: 'none', aspectRatio: '1' }}>
    <img alt="" className="paw-stellar-scene__planet-image" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} decoding="async" draggable={false} ref={imageRef} src={frames[0]} />
  </div>;
}
