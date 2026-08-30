import { lazy, Suspense } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/app/query-client';
import { ControlTransportProvider } from '@/app/control-transport';
import { ControlConnectionMonitor } from '@/app/control-connection-monitor';
import { GlobalFeedbackProvider } from '@/components/feedback';
import { ToastProvider, TooltipProvider } from '@/components/primitives';
import { MotionProvider } from '@/design/motion';
import { PawOsAppearanceProvider } from '@/design/paw-os-themes';
import { ThemeProvider } from '@/design/themes';
import { useFilePreviewStore } from '@/features/agent/file-preview/file-preview-store';
import { ProductIdentityProvider } from '@/features/identity/product-identity';
import { resolveFrontendProduct, type FrontendProduct } from './frontend-product';
import '@/design/tokens.css';
import '@/design/typography.css';
import '@/design/workspace.css';
import '@/components/primitives/primitives.css';
import '@/components/primitives/showcase.css';
import '@/components/feedback/feedback.css';
import '@/components/layout/layout.css';

const FilePreviewHost = lazy(async () => ({
  default: (await import('@/features/agent/file-preview/FilePreviewHost')).FilePreviewHost,
}));

const PawOsApp = lazy(async () => ({
  default: (await import('@/paw-os/PawOsApp')).PawOsApp,
}));

const LegacyProductApp = lazy(async () => ({
  default: (await import('./LegacyProductApp')).LegacyProductApp,
}));

export function App({ frontendProduct }: { frontendProduct?: FrontendProduct } = {}) {
  const product = frontendProduct ?? resolveFrontendProduct({
    configured: import.meta.env.VITE_PAW_FRONTEND,
    search: typeof window === 'undefined' ? '' : window.location.search,
  });

  return (
    <ThemeProvider forcedTheme={product === 'paw-os' ? 'light' : undefined}>
      <PawOsAppearanceProvider>
        <MotionProvider>
        <TooltipProvider delayDuration={350}>
          <ToastProvider>
            <GlobalFeedbackProvider>
              <ControlTransportProvider>
                <ControlConnectionMonitor />
                <FilePreviewLayer />
                <QueryClientProvider client={queryClient}>
                  <ProductIdentityProvider>
                    <Suspense fallback={<ProductLoading />}>
                      {product === 'paw-os' ? (
                        <PawOsApp />
                      ) : (
                        <LegacyProductApp />
                      )}
                    </Suspense>
                  </ProductIdentityProvider>
                </QueryClientProvider>
              </ControlTransportProvider>
            </GlobalFeedbackProvider>
          </ToastProvider>
        </TooltipProvider>
        </MotionProvider>
      </PawOsAppearanceProvider>
    </ThemeProvider>
  );
}

function ProductLoading() {
  return <div aria-label="正在打开产品" className="route-loading" role="status" />;
}

function FilePreviewLayer() {
  const open = useFilePreviewStore((state) => state.open);
  if (!open) return null;
  return <Suspense fallback={null}><FilePreviewHost /></Suspense>;
}
