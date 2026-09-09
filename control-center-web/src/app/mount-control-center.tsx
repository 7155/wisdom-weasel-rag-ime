import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '@/app/App';
import { AppErrorBoundary } from '@/app/AppErrorBoundary';
import { bootstrapControlCenter } from '@/app/bootstrap';
import { registerProductExtensionHosts } from '@/app/register-extension-hosts';

export function mountControlCenter(root: HTMLElement): void {
  bootstrapControlCenter();
  registerProductExtensionHosts();

  createRoot(root).render(
    <StrictMode>
      <AppErrorBoundary>
        <App />
      </AppErrorBoundary>
    </StrictMode>,
  );
}
