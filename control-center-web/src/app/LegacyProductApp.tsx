import { RouterProvider } from 'react-router-dom';
import { router } from '@/app/router';
import { FrontendShell } from './FrontendShell';

/** Legacy Control Center boundary. PAWOS never evaluates the route registry,
 * feature pages, or AppShell unless this product is explicitly selected. */
export function LegacyProductApp() {
  return <FrontendShell><RouterProvider router={router} /></FrontendShell>;
}
