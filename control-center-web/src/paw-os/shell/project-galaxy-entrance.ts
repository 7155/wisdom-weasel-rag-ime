/** A one-shot spatial disclosure. It conveys opening, never Runtime activity. */
export function starfieldEntrance(elapsedS: number, index: number, reduced: boolean) {
  const progress = reduced ? 1 : Math.min(1, Math.max(0, (elapsedS - Math.min(index, 11) * .045) / 1.25));
  if (progress === 1) return { radius: 1, scale: 1, phase: 0, complete: true };
  const remaining = Math.pow(1 - progress, 3);
  return { radius: 1 - remaining * .94, scale: 1 - remaining * .82, phase: -remaining * 1.8, complete: progress === 1 };
}
