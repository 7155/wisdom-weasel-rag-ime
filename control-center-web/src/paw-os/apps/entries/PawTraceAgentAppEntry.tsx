import { useEffect, useRef } from 'react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { TraceAgentFeature } from '@/features/trace-agent';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';

export default function PawTraceAgentApp({ initialRoute = '/trace-agent' }: { initialRoute?: string }) {
  return <div className="paw-trace-agent-app" data-app-id="trace-agent"><MemoryRouter initialEntries={[initialRoute || '/trace-agent']}><TraceRouteBridge initialRoute={initialRoute || '/trace-agent'} /><TraceAgentFeature /></MemoryRouter></div>;
}

/** Keep drafts mounted on internal navigation while accepting outside handoffs. */
function TraceRouteBridge({ initialRoute }: { initialRoute: string }) {
  const desktop = usePawOsDesktop();
  const location = useLocation();
  const navigate = useNavigate();
  const previousInitialRoute = useRef(initialRoute);
  const route = `${location.pathname}${location.search}${location.hash}`;
  useEffect(() => {
    // `initialRoute` is the desktop-owned handoff boundary. Once the Trace
    // window is mounted, its MemoryRouter owns tab/report navigation. Sending
    // every internal `?view=` change back through the desktop reopened the
    // same window and dropped the route before the page could render.
    if (previousInitialRoute.current !== initialRoute) {
      previousInitialRoute.current = initialRoute;
      if (route !== initialRoute) navigate(initialRoute, { replace: true });
    }
  }, [initialRoute, navigate, route]);
  return null;
}
