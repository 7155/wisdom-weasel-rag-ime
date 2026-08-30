/* The Wayfinder's drawn icon language. One 64px grid, one 2.6px round-cap
 * stroke, one 5px corner geometry across the whole family: project folders,
 * conversation files and their Room stack variant. Colour arrives through a
 * single `--paw-work-accent` custom property on the wrapping art box, so a
 * project keeps its own tint and a state change (running/attention) recolours
 * the whole glyph by re-pointing that one variable. No emoji, no system
 * clip-art — every path below is drawn for this desktop. */

export type PawWorkFileKind = 'session' | 'room';

/* Conversation files keep the product's existing semantic colours: moss for a
 * Session, ochre for a Room. Folders instead derive a stable per-project tint
 * from the project id, so neighbouring projects never share a colour by
 * accident and a project's folder keeps its identity across reloads. */
export const PAW_WORK_FILE_ACCENT: Record<PawWorkFileKind, string> = {
  session: '#3f7658',
  room: '#a67d3d',
};

const PAW_WORK_PROJECT_ACCENTS = ['#2f6bff', '#0f8b80', '#3f7658', '#a67d3d', '#b45d4b', '#6d5bd0'] as const;

export function pawWorkProjectAccent(projectId: string): string {
  let hash = 0;
  for (let index = 0; index < projectId.length; index += 1) {
    hash = (hash * 31 + projectId.charCodeAt(index)) >>> 0;
  }
  return PAW_WORK_PROJECT_ACCENTS[hash % PAW_WORK_PROJECT_ACCENTS.length]!;
}

/* PAWOS folders use the same soft, light-catching material as App identity
 * tiles without becoming another rounded square. A saturated back plate,
 * cool front sheet and two integrated edge highlights create the depth; the
 * open state reveals paper but keeps the same optical footprint. */
const FOLDER_BACK = 'M7.5 23 V19.5 C7.5 16.2 10.2 13.5 13.5 13.5 H25.3 L30.3 19 H51.5 C54.8 19 57.5 21.7 57.5 25 V47.5 C57.5 51.4 54.4 54.5 50.5 54.5 H14.5 C10.6 54.5 7.5 51.4 7.5 47.5 Z';
const FOLDER_FRONT_CLOSED = 'M7.5 28.5 C7.5 25.7 9.7 23.5 12.5 23.5 H53.5 C56.2 23.5 58.2 26 57.6 28.6 L53.1 50.1 C52.6 52.7 50.3 54.5 47.6 54.5 H13.8 C10.4 54.5 7.5 51.7 7.5 48.2 Z';
const FOLDER_FRONT_OPEN = 'M8 31 C8 28.2 10.2 26 13 26 H53.5 C56.1 26 58 28.3 57.3 30.8 L52.8 50.2 C52.2 52.8 49.9 54.5 47.2 54.5 H14 C10.6 54.5 8 51.8 8 48.4 Z';
const FOLDER_PAPER = 'M14 26 C14 22.7 16.7 20 20 20 H44.5 C47.8 20 50.5 22.7 50.5 26 V40 H14 Z';

export function PawWorkFolderIcon({ open = false }: { open?: boolean }) {
  return (
    <svg aria-hidden="true" className="paw-work-glyph paw-work-glyph--folder" focusable="false" viewBox="0 0 64 64">
      <path className="paw-work-glyph__back" d={FOLDER_BACK} />
      {open ? <path className="paw-work-glyph__paper" d={FOLDER_PAPER} /> : null}
      <path className="paw-work-glyph__front" d={open ? FOLDER_FRONT_OPEN : FOLDER_FRONT_CLOSED} />
      <path className="paw-work-glyph__folder-sheen" d={open ? 'M11 32 C18 29 43 29 54 31 L53.2 35 C39 32.8 24 32.8 10.4 35 Z' : 'M10.5 29 C21 25.7 45 25.7 55 28.5 L54.2 32.5 C41 30 23 30 9.8 33 Z'} />
      <path className="paw-work-glyph__folder-edge" d={open ? 'M12 31 H53.5' : 'M11.5 28.5 H54.5'} />
      <path className="paw-work-glyph__highlight" d="M14 51.2 H47" />
    </svg>
  );
}

/* A conversation file: one paper sheet with a dog-ear, and the transcript cue
 * — three staggered round-cap lines plus the small continuing-conversation
 * dot. A Room is the same sheet with a second page peeking behind it: two
 * voices, one object. */
const FILE_PAGE = 'M16 12 Q16 8 20 8 H38.5 L48 17.5 V52 Q48 56 44 56 H20 Q16 56 16 52 Z';
const FILE_PAGE_BACK = 'M22 9 Q22 5 26 5 H42 L52 15 V48 Q52 52 48 52 H26 Q22 52 22 48 Z';
const FILE_FOLD = 'M38.5 8 L48 17.5 H42.5 Q38.5 17.5 38.5 13.5 Z';
const FILE_LINES = 'M23 27 H40 M23 33 H37';

export function PawWorkFileIcon({ kind }: { kind: PawWorkFileKind }) {
  return (
    <svg aria-hidden="true" className="paw-work-glyph paw-work-glyph--file" data-file-kind={kind} focusable="false" viewBox="0 0 64 64">
      {kind === 'room' ? <path className="paw-work-glyph__page-back" d={FILE_PAGE_BACK} /> : null}
      <path className="paw-work-glyph__page" d={FILE_PAGE} />
      <path className="paw-work-glyph__fold" d={FILE_FOLD} />
      <path className="paw-work-glyph__lines" d={FILE_LINES} />
      {kind === 'room' ? (
        <g className="paw-work-glyph__room-mark">
          <circle cx="27" cy="42" r="2.3" />
          <circle cx="37" cy="42" r="2.3" />
          <path d="M22.5 49 Q27 45 31.5 49 M32.5 49 Q37 45 41.5 49" />
        </g>
      ) : (
        <path className="paw-work-glyph__session-mark" d="M23 40 H40 Q43 40 43 43 V46 Q43 49 40 49 H31 L27 52 V49 H23 Q20 49 20 46 V43 Q20 40 23 40 Z" />
      )}
    </svg>
  );
}
