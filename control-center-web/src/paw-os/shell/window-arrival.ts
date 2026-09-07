import './window-arrival.css';

/** One brief spatial opening cue. Drag/overview retain the outer transform. */
export function animateWindowArrival(surface: HTMLElement): (() => void) | undefined {
  const preference = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const still = () => preference?.matches || document.documentElement.dataset.reduceMotion === 'true';
  if (typeof surface.animate !== 'function' || still() || document.hidden) return undefined;

  const particles = document.createElement('div');
  particles.className = 'paw-window-arrival-dust';
  particles.setAttribute('aria-hidden', 'true');
  surface.append(particles);
  const arrival = surface.animate([
    { opacity: .72, transform: 'perspective(1100px) translate3d(0, 12px, -24px) rotateX(2deg) scale(.97)', transformOrigin: '50% 75%' },
    { opacity: 1, transform: 'perspective(1100px) translate3d(0, 0, 0) rotateX(0deg) scale(1)', transformOrigin: '50% 75%' },
  ], { duration: 240, easing: 'cubic-bezier(.16, 1, .3, 1)' });
  const dust = particles.animate([
    { opacity: .8, transform: 'scale(.92)' },
    { opacity: 0, transform: 'scale(1.035)' },
  ], { duration: 240, easing: 'cubic-bezier(.2, .7, .3, 1)' });
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    arrival.cancel();
    dust.cancel();
    particles.remove();
    surface.removeEventListener('pointerdown', finish);
    document.removeEventListener('keydown', finish);
    document.removeEventListener('visibilitychange', visibilityChanged);
    preference?.removeEventListener?.('change', motionChanged);
    settings.disconnect();
  };
  const visibilityChanged = () => { if (document.hidden) finish(); };
  const motionChanged = () => { if (still()) finish(); };
  const settings = new MutationObserver(motionChanged);
  settings.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduce-motion'] });
  surface.addEventListener('pointerdown', finish, { once: true });
  document.addEventListener('keydown', finish, { once: true });
  document.addEventListener('visibilitychange', visibilityChanged);
  preference?.addEventListener?.('change', motionChanged);
  void arrival.finished.then(finish, finish);
  return finish;
}
