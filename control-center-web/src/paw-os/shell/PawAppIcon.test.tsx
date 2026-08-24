import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { pawApps } from '../runtime/app-registry';
import { PawAppIcon, PawBrandMark } from './PawAppIcon';

afterEach(cleanup);

describe('PAWOS App identity icons', () => {
  it('ships an independent colour silhouette for every App surface plus the Room mode', () => {
    const identities = [...pawApps.map((app) => ({ id: app.id, label: app.label })), { id: 'room' as const, label: 'Room' }];
    const { container } = render(<>{identities.map((identity) => <PawAppIcon appId={identity.id} key={identity.id} title={identity.label} />)}</>);
    const icons = [...container.querySelectorAll<SVGElement>('[data-paw-app-icon]')];
    expect(icons).toHaveLength(12);
    expect(new Set(icons.map((icon) => icon.getAttribute('data-paw-app-icon'))).size).toBe(12);
    expect(icons.every((icon) => icon.querySelector(`[data-paw-icon-silhouette="${icon.getAttribute('data-paw-app-icon')}"]`))).toBe(true);
    expect(new Set(icons.map((icon) => icon.querySelector('[data-paw-icon-silhouette]')?.innerHTML)).size).toBe(12);
    expect(new Set(icons.map((icon) => icon.getAttribute('data-paw-icon-color'))).size).toBe(12);
    expect(container.querySelector('.paw-app-icon__tile, [data-paw-icon-sheen]')).toBeNull();
    expect(container.querySelector('rect[width="45"][height="45"][rx="11.5"]')).toBeNull();
    expect(container.querySelector('[data-lucide]')).toBeNull();
    expect(container.querySelector('.paw-os-app-icon, .paw-app-glyph')).toBeNull();
  });

  it('keeps every identity intentionally sparse without a shared container', () => {
    const { container } = render(<>{[...pawApps.map((app) => app.id), 'room' as const].flatMap((appId) => [16, 32].map((size) => <PawAppIcon appId={appId} key={`${appId}-${size}`} size={size} />))}</>);
    expect(container.querySelector('[class*="__tile"], [class*="__plate"], [class*="__rail"], [class*="__signal"], [class*="__sheen"]')).toBeNull();
    for (const silhouette of container.querySelectorAll('[data-paw-icon-silhouette]')) {
      expect(silhouette.children.length).toBeGreaterThanOrEqual(2);
      expect(silhouette.children.length).toBeLessThanOrEqual(4);
    }
  });

  it('gives Room a visible identity while keeping it inside the Agent App registry', () => {
    const { container } = render(<><PawAppIcon appId="agent" title="Agent" /><PawAppIcon appId="room" title="Room" /></>);
    expect(pawApps).toHaveLength(11);
    expect(container.querySelector('[data-paw-app-icon="agent"]')).toBeInTheDocument();
    expect(container.querySelector('[data-paw-app-icon="room"]')).toBeInTheDocument();
    expect(pawApps.map((app) => app.id)).not.toContain('room');
    expect(container.querySelector('[data-paw-app-icon="agent"]')).toHaveAttribute('data-paw-icon-color', '#0a84ff');
    expect(container.querySelector('[data-paw-app-icon="room"]')).toHaveAttribute('data-paw-icon-color', '#7a5af8');
  });

  it('is decorative by default and named when a title is supplied', () => {
    const { rerender, getByRole } = render(<PawAppIcon appId="browser" />);
    expect(document.querySelector('[data-paw-app-icon="browser"]')).toHaveAttribute('aria-hidden', 'true');
    rerender(<PawAppIcon appId="browser" title="Browser" />);
    expect(getByRole('img', { name: 'Browser' })).toBeInTheDocument();
  });

  it('keeps the identity legible and explicitly identifies compact placement', () => {
    const { container } = render(<><PawAppIcon appId="memory" size={16} /><PawAppIcon appId="memory" size={32} /></>);
    const [small, large] = [...container.querySelectorAll<SVGElement>('[data-paw-app-icon="memory"]')];
    expect(small).toHaveAttribute('viewBox', '0 0 48 48');
    expect(large).toHaveAttribute('viewBox', '0 0 48 48');
    expect(small).toHaveAttribute('width', '16');
    expect(small).toHaveAttribute('height', '16');
    expect(small).toHaveAttribute('data-paw-icon-scale', 'small');
    expect(large).not.toHaveAttribute('data-paw-icon-scale');
    expect(small?.querySelector('[data-paw-icon-silhouette="memory"]')).toHaveAttribute('data-paw-icon-variant', 'compact');
    expect(large?.querySelector('[data-paw-icon-silhouette="memory"]')).toHaveAttribute('data-paw-icon-variant', 'full');
    expect(small?.querySelector('[data-paw-icon-silhouette="memory"]')?.children.length).toBeGreaterThanOrEqual(2);
    expect(small).toHaveAttribute('focusable', 'false');
  });

  it('preserves each independent silhouette and mark at every shipping size', () => {
    const sizes = [16, 24, 32, 48];
    const { container } = render(<>{pawApps.flatMap((app) => sizes.map((size) => (
      <PawAppIcon appId={app.id} key={`${app.id}-${size}`} size={size} />
    )))}</>);

    for (const app of pawApps) {
      const icons = [...container.querySelectorAll<SVGElement>(`[data-paw-app-icon="${app.id}"]`)];
      expect(icons).toHaveLength(sizes.length);
      for (const [index, icon] of icons.entries()) {
        expect(icon).toHaveAttribute('width', String(sizes[index]));
        expect(icon.querySelector(`[data-paw-icon-silhouette="${app.id}"]`)).toBeInTheDocument();
        expect(icon.querySelector('.paw-app-icon__tile, [data-paw-icon-sheen]')).toBeNull();
      }
    }
  });

  it('gives Room the solar orbit identity and Agent a connection node instead of a face', () => {
    const { container } = render(<><PawAppIcon appId="room" /><PawAppIcon appId="agent" /></>);
    const room = container.querySelector('[data-paw-icon-silhouette="room"]');
    expect(room?.querySelector('ellipse.paw-app-icon__ring')).toBeInTheDocument();
    expect(room?.querySelectorAll('circle')).toHaveLength(2);
    const agent = container.querySelector('[data-paw-icon-silhouette="agent"]');
    expect(agent?.querySelector('circle.paw-app-icon__secondary')).toBeInTheDocument();
    expect(agent?.querySelector('[class*="face"], [class*="avatar"]')).toBeNull();
  });

  it('ships the monochrome paw-print system mark outside the App colour system', () => {
    const { container, getByRole, rerender } = render(<PawBrandMark />);
    const mark = container.querySelector('svg.paw-brand-mark');
    expect(mark).toHaveAttribute('aria-hidden', 'true');
    expect(mark).toHaveAttribute('fill', 'currentColor');
    expect(mark?.querySelectorAll('ellipse, path')).toHaveLength(4);
    expect(mark?.hasAttribute('data-paw-app-icon')).toBe(false);
    rerender(<PawBrandMark title="PAW" />);
    expect(getByRole('img', { name: 'PAW' })).toBeInTheDocument();
  });

  it('stays decorative inside a disabled owner while preserving the App identity', () => {
    const { container } = render(<button disabled type="button"><PawAppIcon appId="system-settings" size={18} />Settings</button>);
    expect(container.querySelector('button')).toBeDisabled();
    expect(container.querySelector('[data-paw-app-icon="system-settings"]')).toHaveAttribute('aria-hidden', 'true');
    expect(container.querySelector('[data-paw-app-icon="system-settings"]')).toHaveAttribute('data-paw-icon-scale', 'small');
  });
});
