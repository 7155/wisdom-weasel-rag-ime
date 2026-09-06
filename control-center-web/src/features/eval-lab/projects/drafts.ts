import type { ArtifactDraft } from './ArtifactSurface';
import { object } from './types';

export function readArtifactDrafts(connection: string): Record<string, ArtifactDraft> {
  try {
    const saved = object(JSON.parse(sessionStorage.getItem(`paw.lab.artifact-drafts.v1:${connection}`) ?? '{}'));
    return Object.fromEntries(Object.entries(saved).filter(([, value]) => {
      const draft = object(value);
      return Number.isSafeInteger(draft.revision) && Number(draft.revision) > 0 && Object.hasOwn(draft, 'content')
        && (draft.raw === undefined || typeof draft.raw === 'string');
    })) as Record<string, ArtifactDraft>;
  } catch { return {}; }
}
export function writeArtifactDrafts(connection: string, drafts: Record<string, ArtifactDraft>): boolean {
  try {
    const key = `paw.lab.artifact-drafts.v1:${connection}`;
    if (Object.keys(drafts).length) sessionStorage.setItem(key, JSON.stringify(drafts));
    else sessionStorage.removeItem(key);
    return true;
  } catch { return false; }
}
