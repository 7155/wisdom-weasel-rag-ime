import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { queryClient } from '@/app/query-client';
import { router } from '@/app/router';
import { ControlTransportProvider } from '@/app/control-transport';
import { ControlConnectionMonitor } from '@/app/control-connection-monitor';
import { GlobalFeedbackProvider } from '@/components/feedback';
import { AppShell } from '@/components/layout';
import { ToastProvider, TooltipProvider } from '@/components/primitives';
import { MotionProvider } from '@/design/motion';
import { ThemeProvider } from '@/design/themes';
import '@/design/tokens.css';
import '@/design/typography.css';
import '@/components/primitives/primitives.css';
import '@/components/primitives/showcase.css';
import '@/components/feedback/feedback.css';
import '@/components/layout/layout.css';

export function App() {
  return (
    <ThemeProvider>
      <MotionProvider>
        <TooltipProvider delayDuration={350}>
          <ToastProvider>
            <GlobalFeedbackProvider>
              <ControlTransportProvider>
                <ControlConnectionMonitor />
                <QueryClientProvider client={queryClient}>
                  <AppShell>
                    <RouterProvider router={router} />
                  </AppShell>
                </QueryClientProvider>
              </ControlTransportProvider>
            </GlobalFeedbackProvider>
          </ToastProvider>
        </TooltipProvider>
      </MotionProvider>
    </ThemeProvider>
  );
}
