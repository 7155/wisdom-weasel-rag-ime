import { ArrowDown, ArrowUp, Search, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import './browser-chrome.css';

export type BrowserFindMatch = { activeMatchOrdinal: number; matches: number } | null;

/**
 * In-page find with a truthful match position. The counter renders only what
 * the guest actually reported through `found-in-page`; while a query has no
 * report yet it stays empty instead of inventing a count.
 */
export function BrowserFindBar({
  match,
  onChange,
  onClose,
  onNext,
  onPrevious,
  value,
}: {
  match: BrowserFindMatch;
  onChange(value: string): void;
  onClose(): void;
  onNext(): void;
  onPrevious(): void;
  value: string;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  return (
    <div className="paw-browser-find" role="search">
      <Search aria-hidden="true" className="paw-browser-find__icon" size={13} />
      <input
        aria-label="页内查找"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            if (event.shiftKey) onPrevious();
            else onNext();
          }
          if (event.key === 'Escape') onClose();
        }}
        placeholder="查找网页内容"
        ref={inputRef}
        spellCheck={false}
        value={value}
      />
      <span aria-live="polite" className="paw-browser-find__count">{value ? findCountText(match) : ''}</span>
      <button aria-label="上一个匹配项" disabled={!value} onClick={onPrevious} type="button"><ArrowUp size={13} /></button>
      <button aria-label="下一个匹配项" disabled={!value} onClick={onNext} type="button"><ArrowDown size={13} /></button>
      <button aria-label="关闭页内查找" onClick={onClose} type="button"><X size={13} /></button>
    </div>
  );
}

function findCountText(match: BrowserFindMatch): string {
  if (!match) return '';
  if (!match.matches) return '无匹配';
  return `${match.activeMatchOrdinal}/${match.matches}`;
}
