import { CircleAlert } from 'lucide-react';
import {
  crashReasonText,
  pageFailureText,
  type BrowserPageFailure,
} from '@/paw-os/apps/paw-browser-model';
import './browser-chrome.css';

/**
 * Truthful page failure surface for the shared Electron guest. It names what
 * actually failed (guest process gone or a main-frame load error) and offers
 * one real recovery: reloading the same page in the same guest.
 */
export function BrowserPageStatus({
  crashedReason,
  failure,
  onRetry,
}: {
  crashedReason?: string;
  failure?: BrowserPageFailure | null;
  onRetry(): void;
}) {
  const status = crashedReason
    ? { title: crashReasonText(crashedReason), detail: '页面进程已结束，可以重新加载。' }
    : failure
      ? pageFailureText(failure)
      : null;
  if (!status) return null;
  const failedUrl = crashedReason ? '' : failure?.url ?? '';
  return (
    <div className="paw-browser-page-status">
      <div className="paw-browser-page-card" role="alert">
        <CircleAlert size={16} />
        <span>
          <strong>{status.title}</strong>
          {status.detail ? <small>{status.detail}</small> : null}
          {failedUrl ? <small className="paw-browser-page-card-url">{failedUrl}</small> : null}
        </span>
        <button onClick={onRetry} type="button">重新加载</button>
      </div>
    </div>
  );
}
