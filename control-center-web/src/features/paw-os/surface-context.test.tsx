import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  PawOsAppSurfaceProvider,
  usePawOsAppSurface,
} from './surface-context';

function Probe() {
  const surface = usePawOsAppSurface();
  return (
    <output data-active={surface?.active === false ? 'false' : 'true'}>
      {surface
        ? `${surface.appId}:${surface.width}x${surface.height}:${surface.compact ? 'compact' : 'regular'}`
        : 'legacy'}
    </output>
  );
}

describe('PawOsAppSurfaceProvider', () => {
  it('exposes window-local geometry to an App presentation', () => {
    render(
      <PawOsAppSurfaceProvider appId="agent" width={700} height={560}>
        <Probe />
      </PawOsAppSurfaceProvider>,
    );

    expect(screen.getByText('agent:700x560:compact')).toBeInTheDocument();
  });

  it('keeps legacy routes outside the PAWOS presentation contract', () => {
    render(<Probe />);

    expect(screen.getByText('legacy')).toBeInTheDocument();
  });

  it('projects whether the owning window is currently interactive', () => {
    render(
      <PawOsAppSurfaceProvider active={false} appId="agent" width={900} height={600}>
        <Probe />
      </PawOsAppSurfaceProvider>,
    );

    expect(screen.getByText('agent:900x600:regular')).toHaveAttribute('data-active', 'false');
  });
});
