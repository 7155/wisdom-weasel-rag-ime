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

/* A folder with a left tab and a lighter front sheet. The open state hinges
 * the front sheet toward the viewer and lets one paper sheet peek out of the
 * opening — the same silhouette, so a folder never jumps shape when its
 * window opens. */
const FOLDER_BACK = 'M11 19 Q11 14 15.5 14 H25 Q27.2 14 28.7 15.8 L31.5 19.6 Q32.2 20.5 33.3 20.5 H52.5 Q57 20.5 57 25 V46.5 Q57 51.5 52 51.5 H16 Q11 51.5 11 46.5 Z';
const FOLDER_FRONT_CLOSED = 'M11 27.5 Q11 23 15.5 23 H52.5 Q57 23 57 27.5 V46.5 Q57 51.5 52 51.5 H16 Q11 51.5 11 46.5 Z';
const FOLDER_FRONT_OPEN = 'M11 27.5 Q11 23 15.5 23 H52.5 Q57 23 57 27.5 L53.8 46.5 Q53 51.5 48 51.5 H16 Q11 51.5 11 46.5 Z';
const FOLDER_PAPER = 'M17.5 23 Q17.5 20 21 20 H43 Q46.5 20 46.5 23 V33 H17.5 Z';

export function PawWorkFolderIcon({ open = false }: { open?: boolean }) {
  return (
    <svg aria-hidden="true" className="paw-work-glyph paw-work-glyph--folder" focusable="false" viewBox="0 0 64 64">
      <path className="paw-work-glyph__back" d={FOLDER_BACK} />
      {open ? <path className="paw-work-glyph__paper" d={FOLDER_PAPER} /> : null}
      <path className="paw-work-glyph__front" d={open ? FOLDER_FRONT_OPEN : FOLDER_FRONT_CLOSED} />
    </svg>
  );
}

/* A conversation file: one paper sheet with a dog-ear, and the transcript cue
 * — three staggered round-cap lines plus the small continuing-conversation
 * dot. A Room is the same sheet with a second page peeking behind it: two
 * voices, one object. */
const FILE_PAGE = 'M19 11 Q19 8 22 8 H38.5 L47 16.5 V52 Q47 55 44 55 H22 Q19 55 19 52 Z';
const FILE_PAGE_BACK = 'M23 9 Q23 5 27 5 H42.5 L51 13.5 V47 Q51 51 47 51 H27 Q23 51 23 47 Z';
const FILE_FOLD = 'M38.5 8 L47 16.5 H41.5 Q38.5 16.5 38.5 13.5 Z';
const FILE_LINES = 'M25 28 H39 M25 34 H43 M25 40 H33';

export function PawWorkFileIcon({ kind }: { kind: PawWorkFileKind }) {
  return (
    <svg aria-hidden="true" className="paw-work-glyph paw-work-glyph--file" focusable="false" viewBox="0 0 64 64">
      {kind === 'room' ? <path className="paw-work-glyph__page-back" d={FILE_PAGE_BACK} /> : null}
      <path className="paw-work-glyph__page" d={FILE_PAGE} />
      <path className="paw-work-glyph__fold" d={FILE_FOLD} />
      <path className="paw-work-glyph__lines" d={FILE_LINES} />
      <circle className="paw-work-glyph__cursor" cx="39.5" cy="40" r="1.7" />
    </svg>
  );
}
