import { describe, expect, it } from 'vitest';
import appSource from '@/app/App.tsx?raw';
import structuredRenderersSource from '@/features/agent/timeline/StructuredRenderers.tsx?raw';
import workDocumentsCss from '@/features/work-documents/work-documents.css?raw';
import httpTransportSource from '@/platform/http-transport.ts?raw';
import nativeTransportSource from '@/platform/native-transport.ts?raw';
import pawOsSource from './PawOsApp.tsx?raw';
import appDispatcherSource from './apps/PawApps.tsx?raw';
import runtimeSource from './apps/PawAppsRuntime.tsx?raw';
import desktopSource from './shell/PawDesktop.tsx?raw';
import windowLayerSource from './shell/PawWindowLayer.tsx?raw';
import agentFxCss from './styles/paw-os-agent-fx.css?raw';

describe('PAWOS production loading boundaries', () => {
  it('keeps the legacy router out of the default PAWOS product entry', () => {
    expect(appSource).not.toContain("import { RouterProvider } from 'react-router-dom'");
    expect(appSource).not.toContain("import { RouteLoading, router } from '@/app/router'");
    expect(appSource).not.toContain("import { FrontendShell } from './FrontendShell'");
    expect(appSource).toContain("import('./LegacyProductApp')");
  });

  it('loads every leaf App through a dynamic boundary instead of the total dispatcher', () => {
    for (const staticOwner of [
      "from './PawAgentApp'",
      "from './PawBrowserApp'",
      "from './PawNativeApps'",
      "from '@/features/paw-os/PawOsSatelliteHost'",
      "from '@/features/paw-os/PawResultWindow'",
    ]) {
      expect(runtimeSource).not.toContain(staticOwner);
    }
    for (const lazyEntry of [
      './entries/PawAgentAppEntry',
      './entries/PawBrowserAppEntry',
      './entries/PawNativeAppEntry',
      './entries/PawSatelliteEntry',
      './entries/PawResultWindowEntry',
    ]) {
      expect(runtimeSource).toContain(`import('${lazyEntry}')`);
    }
  });

  it('warms the primary Agent boundary before the launch click reaches the main thread', () => {
    expect(appDispatcherSource).toContain('export function warmPawAppProcess');
    expect(runtimeSource).toContain('export function warmPawAppBody');
    expect(desktopSource).toContain("warmPawAppProcess('agent')");
    expect(desktopSource).toContain('onPointerEnter={() => warmPawAppProcess(appId)}');
    expect(desktopSource).toContain('onFocus={() => warmPawAppProcess(appId)}');
  });

  it('keeps App-only visual layers out of the first PAWOS shell stylesheet', () => {
    for (const appStyle of [
      'paw-os-agent-composition.css',
      'paw-os-agent-next.css',
      'paw-os-agent-migrated-v1.css',
      'paw-os-agent-fx.css',
      'paw-os-room-migrated-v1.css',
      'paw-os-room-focus.css',
      'paw-os-starfield.css',
      'paw-os-sys-apps-migrated-v1.css',
      'paw-os-tools-files-migrated-v1.css',
    ]) {
      expect(pawOsSource).not.toContain(appStyle);
    }
  });

  it('defers the generated contract runtime and Room keepalive reducer beyond the first shell', () => {
    for (const transportSource of [nativeTransportSource, httpTransportSource]) {
      expect(transportSource).not.toContain("from '@/contracts/validators'");
      expect(transportSource).toContain('loadContractValidationRuntime');
    }
    expect(windowLayerSource).not.toContain("from '@/features/rooms/runtime/use-room-live-session'");
    expect(windowLayerSource).not.toContain("from '@/features/rooms/state/live-store'");
    expect(windowLayerSource).toContain("from '@/features/rooms/state/projection-bridge'");
    expect(windowLayerSource).toContain("lazy(() => import('./PawRoomProjectionKeeper'))");
  });

  it('keeps disclosure spacing and live progress updates off layout properties', () => {
    expect(workDocumentsCss).not.toMatch(/transition:\s*padding(?:-top)?/);
    expect(agentFxCss).not.toMatch(/transition:\s*width/);
    expect(agentFxCss).toMatch(/\.fx-track \.fill\s*\{[^}]*transform:\s*scaleX\(var\(--fx-progress-scale, 0\)\);[^}]*transition:\s*transform/s);
    expect(structuredRenderersSource).toContain("'--fx-progress-scale': percent / 100");
  });
});
