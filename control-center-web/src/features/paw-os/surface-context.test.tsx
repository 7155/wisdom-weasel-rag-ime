import { act, render, screen } from '@testing-library/react';
import { memo, useState } from 'react';
import { describe, expect, it } from 'vitest';
import {
  PawOsAppSurfaceProvider,
  PawOsDesktopProvider,
  usePawOsAppActive,
  usePawOsAppCompact,
  usePawOsAppIdentity,
  usePawOsAppSurface,
  usePawOsDesktop,
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
function DesktopFocusProbe() {
  return <output data-testid="desktop-focus-group">{usePawOsDesktop()?.collaborationFocusGroup ?? 'none'}</output>;
}


describe('PawOsAppSurfaceProvider', () => {
  it('exposes desktop-owned collaboration focus as a read-only surface control', () => {
    render(
      <PawOsDesktopProvider collaborationFocusGroup="room:room-7" openWindow={() => undefined}>
        <DesktopFocusProbe />
      </PawOsDesktopProvider>,
    );

    expect(screen.getByTestId('desktop-focus-group')).toHaveTextContent('room:room-7');
  });

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

  it('keeps identity, activity and compact selectors isolated from ordinary pixel resize', () => {
    const renders = { active: 0, compact: 0, identity: 0 };
    let updateSurface: ((next: { active: boolean; width: number; height: number }) => void) | undefined;
    const IdentityProbe = memo(function IdentityProbe() {
      renders.identity += 1;
      return <output>{usePawOsAppIdentity()?.windowId}</output>;
    });
    const ActiveProbe = memo(function ActiveProbe() {
      renders.active += 1;
      return <output>{String(usePawOsAppActive())}</output>;
    });
    const CompactProbe = memo(function CompactProbe() {
      renders.compact += 1;
      return <output>{String(usePawOsAppCompact())}</output>;
    });
    function Harness() {
      const [surface, setSurface] = useState({ active: true, width: 900, height: 600 });
      updateSurface = setSurface;
      return (
        <PawOsAppSurfaceProvider appId="agent" active={surface.active} windowId="agent-window" width={surface.width} height={surface.height}>
          <IdentityProbe />
          <ActiveProbe />
          <CompactProbe />
        </PawOsAppSurfaceProvider>
      );
    }

    render(<Harness />);
    expect(renders).toEqual({ identity: 1, active: 1, compact: 1 });

    act(() => updateSurface?.({ active: true, width: 880, height: 590 }));
    expect(renders).toEqual({ identity: 1, active: 1, compact: 1 });

    act(() => updateSurface?.({ active: false, width: 880, height: 590 }));
    expect(renders).toEqual({ identity: 1, active: 2, compact: 1 });

    act(() => updateSurface?.({ active: false, width: 760, height: 590 }));
    expect(renders).toEqual({ identity: 1, active: 2, compact: 2 });
  });
});
