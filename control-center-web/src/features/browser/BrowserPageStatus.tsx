import { Check, CircleAlert, Copy, RotateCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  crashReasonText,
  pageFailureText,
  type BrowserPageFailure,
} from '@/paw-os/apps/paw-browser-model';
import './browser-chrome.css';

/**
 * Truthful page failure surface for the shared Electron guest. It names what
 * actually failed (guest process gone or a main-frame load error), shows the
 * raw evidence (exact URL, net error code, or process exit reason), and
 * offers one real recovery: reloading the same page in the same guest. The
 * only other action copies the failed address; nothing simulates a page.
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
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  useEffect(() => setCopyState('idle'), [crashedReason, failure]);
  const status = crashedReason
    ? { title: crashReasonText(crashedReason), detail: '页面进程已结束，可以重新加载。' }
    : failure
      ? pageFailureText(failure)
      : null;
  if (!status) return null;
  const failedUrl = crashedReason ? '' : failure?.url ?? '';
  // pageFailureText already reports the bare code when there is no
  // description, so the separate evidence line never repeats the detail.
  const evidence = crashedReason
    ? `进程退出原因 ${crashedReason}`
    : failure && failure.description.trim()
      ? `错误代码 ${failure.code}`
      : '';

  const copyFailedUrl = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('剪贴板不可用');
      await navigator.clipboard.writeText(failedUrl);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  };

  return (
    <div className="paw-browser-page-status">
      <div className="paw-browser-page-card" role="alert">
        <span aria-hidden="true" className="paw-browser-page-mark">
          <CircleAlert size={22} />
        </span>
        <strong>{status.title}</strong>
        {status.detail ? <p>{status.detail}</p> : null}
        {failedUrl ? <code className="paw-browser-page-card-url">{failedUrl}</code> : null}
        {evidence ? <small className="paw-browser-page-evidence">{evidence}</small> : null}
        <div className="paw-browser-page-actions">
          <button className="paw-browser-page-retry" onClick={onRetry} type="button">
            <RotateCw size={13} />重新加载
          </button>
          {failedUrl ? (
            <button
              data-copied={copyState === 'copied' || undefined}
              onClick={() => void copyFailedUrl()}
              type="button"
            >
              {copyState === 'copied' ? <Check size={13} /> : <Copy size={13} />}
              {copyState === 'copied' ? '已复制' : copyState === 'failed' ? '复制失败' : '复制网址'}
            </button>
          ) : null}
        </div>
        <small className="paw-browser-page-guest-note">恢复在当前共享标签页内完成，不会打开新的浏览器窗口。</small>
      </div>
    </div>
  );
}
