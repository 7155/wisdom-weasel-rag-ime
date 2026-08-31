import { useId, type ReactNode } from 'react';

/* Desktop work objects use the exact optical grammar in icon-wall.html:
 * 24%-radius colour tile, one 24% top sheen and one bold white silhouette.
 * A project borrows the Files identity, while a conversation projects its
 * canonical Agent or Room identity. Context and labels explain that these are
 * work objects, so a second paper/dog-ear metaphor would only add noise. */

export type PawWorkFileKind = 'session' | 'room';

export const PAW_WORK_FILE_ACCENT: Record<PawWorkFileKind, string> = {
  session: '#0A84FF',
  room: '#7A5AF8',
};

const PAW_WORK_PROJECT_ACCENT = '#F5A623';

export function pawWorkProjectAccent(_projectId: string): string {
  return PAW_WORK_PROJECT_ACCENT;
}

const FILES_FOLDER = 'M9 16.5 a2.5 2.5 0 0 1 2.5-2.5 h8.6 l3.6 4.5 h13.8 a2.5 2.5 0 0 1 2.5 2.5 V33 a4 4 0 0 1-4 4 H13 a4 4 0 0 1-4-4 z';
const AGENT_BUBBLE = 'M10 15 a10 10 0 0 1 10-10 h8 a10 10 0 0 1 10 10 v7 a10 10 0 0 1-10 10 h-9 l-6.5 6 v-6.2 A10 10 0 0 1 10 25 z';

function WorkTile({ children, sheenId }: { children: ReactNode; sheenId: string }) {
  return (
    <>
      <defs>
        <linearGradient id={sheenId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity=".24" />
          <stop offset=".55" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect className="paw-work-glyph__tile" height="45" rx="11.5" width="45" x="1.5" y="1.5" />
      <rect className="paw-work-glyph__tile-sheen" fill={`url(#${sheenId})`} height="45" rx="11.5" width="45" x="1.5" y="1.5" />
      {children}
    </>
  );
}

export function PawWorkFolderIcon({ open = false }: { open?: boolean }) {
  const sheenId = `paw-work-folder-sheen-${useId().replaceAll(':', '')}`;
  return (
    <svg aria-hidden="true" className="paw-work-glyph paw-work-glyph--folder" data-open={open || undefined} focusable="false" viewBox="0 0 48 48">
      <WorkTile sheenId={sheenId}>
        <path className="paw-work-glyph__folder-body" d={FILES_FOLDER} />
        <rect className="paw-work-glyph__folder-divider" height="3" width="31" x="9" y="23.5" />
      </WorkTile>
    </svg>
  );
}

export function PawWorkFileIcon({ kind }: { kind: PawWorkFileKind }) {
  const sheenId = `paw-work-file-sheen-${useId().replaceAll(':', '')}`;
  return (
    <svg aria-hidden="true" className="paw-work-glyph paw-work-glyph--file" data-file-kind={kind} focusable="false" viewBox="0 0 48 48">
      <WorkTile sheenId={sheenId}>
        {kind === 'room' ? (
          <g className="paw-work-glyph__room-voices">
            <circle className="paw-work-glyph__room-voice" cx="19" cy="19" r="8.5" />
            <circle className="paw-work-glyph__room-voice" cx="29" cy="19" r="8.5" />
            <circle className="paw-work-glyph__room-voice" cx="24" cy="28.5" r="8.5" />
          </g>
        ) : (
          <>
            <path className="paw-work-glyph__agent-bubble" d={AGENT_BUBBLE} transform="translate(0 4)" />
            <circle className="paw-work-glyph__agent-core" cx="24" cy="22" r="5.2" />
          </>
        )}
      </WorkTile>
    </svg>
  );
}
