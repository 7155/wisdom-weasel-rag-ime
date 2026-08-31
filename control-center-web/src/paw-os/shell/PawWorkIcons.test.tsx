import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PAW_WORK_FILE_ACCENT, PawWorkFileIcon, PawWorkFolderIcon, pawWorkProjectAccent } from './PawWorkIcons';

describe('PAWOS desktop work icons', () => {
  it('uses the icon-wall Files tile for every project folder', () => {
    const closed = render(<PawWorkFolderIcon />).container;
    const open = render(<PawWorkFolderIcon open />).container;

    expect(pawWorkProjectAccent('project-a')).toBe('#F5A623');
    expect(pawWorkProjectAccent('project-b')).toBe('#F5A623');
    expect(closed.querySelector('svg')).toHaveAttribute('viewBox', '0 0 48 48');
    expect(closed.querySelector('.paw-work-glyph__tile')).toBeInTheDocument();
    expect(closed.querySelector('.paw-work-glyph__tile-sheen')).toBeInTheDocument();
    expect(closed.querySelector('.paw-work-glyph__folder-body')).toBeInTheDocument();
    expect(closed.querySelector('.paw-work-glyph__folder-divider')).toBeInTheDocument();
    expect(open.querySelector('[data-open="true"] .paw-work-glyph__folder-body')).toBeInTheDocument();
    expect(open.querySelector('.paw-work-glyph__folder-paper')).not.toBeInTheDocument();
    expect(open.querySelector('.paw-work-glyph__folder-front')).not.toBeInTheDocument();
  });

  it('reuses the icon-wall Agent bubble and Room voices without a paper document', () => {
    const session = render(<PawWorkFileIcon kind="session" />).container;
    const room = render(<PawWorkFileIcon kind="room" />).container;

    expect(PAW_WORK_FILE_ACCENT).toEqual({ session: '#0A84FF', room: '#7A5AF8' });
    expect(session.querySelector('svg')).toHaveAttribute('viewBox', '0 0 48 48');
    expect(session.querySelector('.paw-work-glyph__tile')).toBeInTheDocument();
    expect(room.querySelector('.paw-work-glyph__tile')).toBeInTheDocument();
    expect(session.querySelector('.paw-work-glyph__tile-sheen')).toBeInTheDocument();
    expect(room.querySelector('.paw-work-glyph__tile-sheen')).toBeInTheDocument();
    expect(session.querySelector('[data-file-kind="session"] .paw-work-glyph__agent-bubble')).toBeInTheDocument();
    expect(session.querySelector('.paw-work-glyph__agent-core')).toBeInTheDocument();
    expect(room.querySelectorAll('[data-file-kind="room"] .paw-work-glyph__room-voice')).toHaveLength(3);
    expect(session.querySelector('.paw-work-glyph__page')).not.toBeInTheDocument();
    expect(room.querySelector('.paw-work-glyph__page-back')).not.toBeInTheDocument();
  });
});
