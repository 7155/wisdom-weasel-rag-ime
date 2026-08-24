import { CornerDownLeft, Globe2, Info, LockKeyhole, Search, X } from 'lucide-react';
import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import {
  normalizedAddress,
  omniboxIconKind,
  omniboxIconTitle,
} from '@/paw-os/apps/paw-browser-model';
import './browser-chrome.css';

const GOOGLE_SEARCH_PREFIX = 'https://www.google.com/search?q=';

export type OmniboxCommitPreview =
  | { kind: 'open'; url: string }
  | { kind: 'search'; query: string; url: string };

/**
 * States exactly what pressing Enter will do with the current draft: open one
 * normalized URL or run one web search. Derived from the same normalization
 * the App uses to navigate, so the preview can never differ from the commit.
 */
export function omniboxCommitPreview(address: string, currentUrl: string): OmniboxCommitPreview | null {
  const committed = currentUrl === 'about:blank' ? '' : currentUrl;
  const draft = address.trim();
  if (!draft || draft === committed) return null;
  const url = normalizedAddress(draft);
  if (!url) return null;
  if (url.startsWith(GOOGLE_SEARCH_PREFIX)) return { kind: 'search', query: draft, url };
  return { kind: 'open', url };
}

export type CommittedUrlParts = { scheme: string; host: string; rest: string };

/**
 * Splits a committed http(s) URL for the resting display so the host can be
 * emphasized. Returns null unless the parts reassemble to the exact committed
 * string, which keeps the styled display equal to the real address.
 */
export function committedUrlParts(url: string): CommittedUrlParts | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
  const scheme = `${parsed.protocol}//`;
  const rest = `${parsed.pathname}${parsed.search}${parsed.hash}`;
  if (`${scheme}${parsed.host}${rest}` !== url) return null;
  return { scheme, host: parsed.host, rest };
}

/**
 * Real omnibox. The leading icon states the truth about the committed page:
 * a lock only for HTTPS, an unencrypted mark for HTTP, and search while the
 * draft differs from the committed URL or nothing is committed yet. While
 * editing, one action row previews the exact URL or search Enter commits;
 * Escape restores the committed address. At rest the committed URL is shown
 * with the host emphasized, without changing the underlying field value.
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
  const inputRef = useRef<HTMLInputElement | null>(null);
  const selectAllOnMouseUp = useRef(false);
  const [focused, setFocused] = useState(false);
  const kind = omniboxIconKind(address, currentUrl);
  const committed = currentUrl === 'about:blank' ? '' : currentUrl;
  const preview = focused ? omniboxCommitPreview(address, currentUrl) : null;
  const restingParts = !focused && address && address === committed ? committedUrlParts(committed) : null;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onNavigate(address);
  };

  const keyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    if (address === committed) {
      inputRef.current?.blur();
      return;
    }
    onAddressChange(committed);
  };

  // First pointer click selects the whole address; a second click keeps the
  // caret where the person placed it. Keyboard focus always selects all.
  const pointerDown = () => {
    if (document.activeElement !== inputRef.current) selectAllOnMouseUp.current = true;
  };
  const focus = () => {
    setFocused(true);
    if (!selectAllOnMouseUp.current) inputRef.current?.select();
  };
  const mouseUp = () => {
    if (!selectAllOnMouseUp.current) return;
    selectAllOnMouseUp.current = false;
    const input = inputRef.current;
    if (input && input.selectionStart === input.selectionEnd) input.select();
  };
  const blur = () => {
    setFocused(false);
    selectAllOnMouseUp.current = false;
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
      <span className="paw-omnibox-field" data-presenting={restingParts ? true : undefined}>
        <input
          aria-label="页面地址"
          onBlur={blur}
          onChange={(event) => onAddressChange(event.target.value)}
          onFocus={focus}
          onKeyDown={keyDown}
          onMouseUp={mouseUp}
          onPointerDown={pointerDown}
          placeholder="输入网址或搜索内容…"
          ref={inputRef}
          spellCheck={false}
          value={address}
        />
        {restingParts ? (
          <span aria-hidden="true" className="paw-omnibox-presentation">
            <span className="paw-omnibox-url-scheme">{restingParts.scheme}</span>
            <span className="paw-omnibox-url-host">{restingParts.host}</span>
            <span className="paw-omnibox-url-rest">{restingParts.rest}</span>
          </span>
        ) : null}
      </span>
      {address ? (
        <button
          aria-label="清除地址"
          className="paw-omnibox-clear"
          onClick={() => {
            onAddressChange('');
            inputRef.current?.focus();
          }}
          onMouseDown={(event) => event.preventDefault()}
          type="button"
        >
          <X size={12} />
        </button>
      ) : null}
      {preview ? (
        <div className="paw-omnibox-commit-hint">
          <button
            aria-label={preview.kind === 'search' ? `搜索 ${preview.query}` : `打开 ${preview.url}`}
            onClick={() => onNavigate(address)}
            onMouseDown={(event) => event.preventDefault()}
            type="button"
          >
            <span aria-hidden="true" className="paw-omnibox-commit-icon">
              {preview.kind === 'search' ? <Search size={13} /> : <Globe2 size={13} />}
            </span>
            <span className="paw-omnibox-commit-text">
              <b>{preview.kind === 'search' ? '搜索' : '打开'}</b>
              <span>{preview.kind === 'search' ? preview.query : preview.url}</span>
              {preview.kind === 'search' ? <small>Google</small> : null}
            </span>
            <kbd aria-hidden="true"><CornerDownLeft size={11} />回车</kbd>
          </button>
        </div>
      ) : null}
    </form>
  );
}
