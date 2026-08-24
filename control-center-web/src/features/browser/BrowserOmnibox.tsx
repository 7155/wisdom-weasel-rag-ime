import { Info, LockKeyhole, Search, X } from 'lucide-react';
import type { FormEvent } from 'react';
import { omniboxIconKind, omniboxIconTitle } from '@/paw-os/apps/paw-browser-model';
import './browser-chrome.css';

/**
 * Real omnibox. The leading icon states the truth about the committed page:
 * a lock only for HTTPS, an unencrypted mark for HTTP, and search while the
 * draft differs from the committed URL or nothing is committed yet.
 */
export function BrowserOmnibox({
  address,
  currentUrl,
  onAddressChange,
  onNavigate,
}: {
  address: string;
  currentUrl: string;
  onAddressChange(value: string): void;
  onNavigate(rawAddress: string): void;
}) {
  const kind = omniboxIconKind(address, currentUrl);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onNavigate(address);
  };
  return (
    <form className="paw-omnibox-form" onSubmit={submit}>
      <span
        className={kind === 'lock' ? 'paw-omnibox-icon paw-lock-icon' : 'paw-omnibox-icon'}
        data-kind={kind}
        title={omniboxIconTitle(kind)}
      >
        {kind === 'lock' ? <LockKeyhole size={13} /> : kind === 'info' ? <Info size={13} /> : <Search size={13} />}
      </span>
      <input
        aria-label="页面地址"
        onChange={(event) => onAddressChange(event.target.value)}
        placeholder="输入网址或搜索内容…"
        spellCheck={false}
        value={address}
      />
      {address ? (
        <button aria-label="清除地址" className="paw-omnibox-clear" onClick={() => onAddressChange('')} type="button">
          <X size={12} />
        </button>
      ) : null}
    </form>
  );
}
