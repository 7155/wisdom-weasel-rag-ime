const frames = Object.entries(import.meta.glob<string>(
  '../assets/stellar/nebula-frames/*.png', { eager: true, query: '?url', import: 'default' },
)).sort(([a], [b]) => a.localeCompare(b)).map(([, url]) => url);

/** Two decoded layers dissolve over the selected interval. Pausing freezes the exact
 * blend; resuming continues it instead of restarting or jumping to a frame. */
export function createStellarStopMotion(target: HTMLImageElement, sequence: readonly string[] = frames, durationMs = 2000) {
  let disposed = false;
  let ready = false;
  let enabled = false;
  let tick = 0;
  let overlay: HTMLImageElement | undefined;
  let animations: Animation[] = [];
  const originalStyle = target.getAttribute('style');
  const plane = target.parentElement;
  const originalIsolation = plane?.style.isolation ?? '';
  const images = sequence.map((src) => { const image = new Image(); image.src = src; return image; });
  const advance = () => {
    if (disposed || !ready || !enabled || !overlay || animations.length || sequence.length < 2) return;
    const nextTick = (tick + 1) % (2 * (sequence.length - 1));
    const index = nextTick < sequence.length ? nextTick : 2 * (sequence.length - 1) - nextTick;
    overlay.src = sequence[index]!;
    // Both layers fade so transparent planet edges never retain the old frame.
    const options: KeyframeAnimationOptions = { duration: durationMs, easing: 'linear', fill: 'forwards' };
    animations = [
      target.animate([{ opacity: 1 }, { opacity: 0 }], options),
      overlay.animate([{ opacity: 0 }, { opacity: 1 }], options),
    ];
    void Promise.all(animations.map((animation) => animation.finished)).then(() => {
      if (disposed) return;
      target.src = sequence[index]!;
      tick = nextTick;
      // Commit the decoded image and remove the finished blend in one task.
      for (const animation of animations) animation.cancel();
      animations = [];
      advance();
    }).catch(() => { /* Cancellation during teardown is expected. */ });
  };
  void Promise.all(images.map(async (image) => image.decode())).then(() => {
    if (disposed || !sequence.length || typeof target.animate !== 'function') return;
    target.src = sequence[0]!;
    target.style.animation = 'none';
    overlay = target.cloneNode(false) as HTMLImageElement;
    overlay.dataset.crossfadeLayer = 'true';
    overlay.style.opacity = '0';
    overlay.style.pointerEvents = 'none';
    // Add complementary premultiplied layers inside their own plane: normal
    // source-over fading would lose brightness/coverage midway through a blend.
    overlay.style.mixBlendMode = 'plus-lighter';
    if (plane) plane.style.isolation = 'isolate';
    target.after(overlay);
    ready = true;
    advance();
  }).catch(() => { /* Keep the static sky when an asset cannot be decoded. */ });
  return {
    setEnabled(value: boolean) {
      if (enabled === value || disposed) return;
      enabled = value;
      for (const animation of animations) { if (enabled) animation.play(); else animation.pause(); }
      advance();
    },
    dispose() {
      disposed = true;
      for (const animation of animations) animation.cancel();
      animations = [];
      overlay?.remove();
      if (plane) plane.style.isolation = originalIsolation;
      if (originalStyle === null) target.removeAttribute('style');
      else target.setAttribute('style', originalStyle);
    },
  };
}
