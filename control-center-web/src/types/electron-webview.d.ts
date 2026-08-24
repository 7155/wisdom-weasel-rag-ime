import type { PawBrowserHost, PawBrowserWebview } from '@/paw-os/apps/paw-browser-host';

declare global {
  interface Window {
    pawBrowserHost?: PawBrowserHost;
  }

  namespace React.JSX {
    interface IntrinsicElements {
      webview: React.DetailedHTMLProps<React.HTMLAttributes<PawBrowserWebview>, PawBrowserWebview> & {
        allowpopups?: boolean | string;
        partition?: string;
        src?: string;
      };
    }
  }
}

export {};
