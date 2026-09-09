import { registerPawExtensionHost } from '@/paw-os/extensions/registry';

// Concrete feature imports belong to product composition, never the OS registry.
// Keep the function identity stable so repeated bootstrap is idempotent.
const loadLabAppHost = () => import('@/features/eval-lab/projects/LabAppHost');

export function registerProductExtensionHosts(): void {
  registerPawExtensionHost('lab-html', loadLabAppHost);
}
