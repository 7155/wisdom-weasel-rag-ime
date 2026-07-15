import type { RouteId } from '@/app/route-registry';

export function RoutePlaceholder({ routeId }: { routeId: RouteId }) {
  return (
    <main data-route-id={routeId}>
      <h1>{routeId}</h1>
    </main>
  );
}
