/**
 * 星空 lazy boundary — the sky is a luxury, never a tax.
 *
 * `PawStarfield` and everything below it (scene model, feed, projections,
 * the WebGL stage and its procedural texture factory) stay out of the Agent
 * home / Room conversation bundle path. The chunk is fetched the first time
 * a user presses the 星空 button; until then the default surfaces pay zero
 * bytes and mount zero starfield code.
 *
 * The boundary deliberately exports thin wrappers instead of the raw
 * `lazy()` components so every caller shares one Suspense fallback: a quiet
 * deep-space boot screen instead of a layout jump.
 */

import { LoaderCircle } from 'lucide-react';
import { lazy, Suspense, type ComponentProps } from 'react';
import type {
  PawRoomStarfield as PawRoomStarfieldComponent,
  PawSessionStarfield as PawSessionStarfieldComponent,
} from './PawStarfield';

const RoomStarfield = lazy(async () => ({
  default: (await import('./PawStarfield')).PawRoomStarfield,
}));

const SessionStarfield = lazy(async () => ({
  default: (await import('./PawStarfield')).PawSessionStarfield,
}));

/** Shown only for the moment the starfield chunk is in flight. */
function StarfieldBoot() {
  return (
    <div className="paw-sf-boot" role="status">
      <LoaderCircle aria-hidden="true" className="ui-spin" size={16} />
      <span>正在点亮星空</span>
    </div>
  );
}

export function LazyPawRoomStarfield(props: ComponentProps<typeof PawRoomStarfieldComponent>) {
  return (
    <Suspense fallback={<StarfieldBoot />}>
      <RoomStarfield {...props} />
    </Suspense>
  );
}

export function LazyPawSessionStarfield(props: ComponentProps<typeof PawSessionStarfieldComponent>) {
  return (
    <Suspense fallback={<StarfieldBoot />}>
      <SessionStarfield {...props} />
    </Suspense>
  );
}
