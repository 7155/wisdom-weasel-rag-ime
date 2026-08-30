import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PawWorkFileIcon, PawWorkFolderIcon } from './PawWorkIcons';

describe('PAWOS desktop work icons', () => {
  it('draws a layered folder with an integrated material highlight instead of a generic outline glyph', () => {
    const { container } = render(<PawWorkFolderIcon />);
    expect(container.querySelector('.paw-work-glyph__back')).toBeInTheDocument();
    expect(container.querySelector('.paw-work-glyph__front')).toBeInTheDocument();
    expect(container.querySelector('.paw-work-glyph__folder-sheen')).toBeInTheDocument();
    expect(container.querySelector('.paw-work-glyph__folder-edge')).toBeInTheDocument();
    expect(container.querySelector('.paw-work-glyph__highlight')).toBeInTheDocument();
  });

  it('keeps Session and Room files recognizably different at icon size', () => {
    const session = render(<PawWorkFileIcon kind="session" />).container;
    const room = render(<PawWorkFileIcon kind="room" />).container;

    expect(session.querySelector('[data-file-kind="session"] .paw-work-glyph__session-mark')).toBeInTheDocument();
    expect(room.querySelector('[data-file-kind="room"] .paw-work-glyph__room-mark')).toBeInTheDocument();
    expect(room.querySelector('.paw-work-glyph__page-back')).toBeInTheDocument();
  });
});
