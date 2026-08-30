import { describe, expect, it } from 'vitest';
import appSource from '@/app/App.tsx?raw';
import httpTransportSource from '@/platform/http-transport.ts?raw';
import nativeTransportSource from '@/platform/native-transport.ts?raw';
import pawOsSource from './PawOsApp.tsx?raw';
import runtimeSource from './apps/PawAppsRuntime.tsx?raw';
import windowLayerSource from './shell/PawWindowLayer.tsx?raw';

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
    expect(windowLayerSource).toContain("lazy(() => import('./PawRoomProjectionKeeper'))");
  });
});
