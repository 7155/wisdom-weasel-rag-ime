import { CircleAlert, Globe2, LoaderCircle, Plus, X } from 'lucide-react';
import './browser-chrome.css';

export type BrowserTabItem = {
  id: string;
  title: string;
  active: boolean;
  loading?: boolean;
  favicon?: string;
  failed?: boolean;
};

/**
 * Real Browser tab strip. Each row mirrors an actual guest/tab: spinner while
 * the page loads, the page's own favicon once known, and a failure mark when
 * the last main-frame load did not commit. Close stays on the selected tab so
 * the strip keeps one close affordance at narrow widths.
 */
export function BrowserTabStrip({
  inWindowChrome,
  newTabDisabled,
  onClose,
  onNewTab,
  onSelect,
  tabs,
}: {
  inWindowChrome?: boolean;
  newTabDisabled?: boolean;
  onClose(tabId: string): void;
  onNewTab(): void;
  onSelect(tabId: string): void;
  tabs: BrowserTabItem[];
}) {
  return (
    <div className="paw-browser-tabstrip" data-window-chrome={inWindowChrome || undefined}>
      <div aria-label="PAW Browser 标签页" className="paw-browser-tabs-live" role="tablist">
        {tabs.map((tab) => (
          <div
            className="paw-browser-tab"
            data-active={tab.active || undefined}
            data-failed={tab.failed || undefined}
            key={tab.id}
            role="presentation"
          >
            <button
              aria-selected={tab.active}
              className="paw-browser-tab-main"
              onClick={() => onSelect(tab.id)}
              role="tab"
              type="button"
            >
              <BrowserTabIcon tab={tab} />
              <span>{tab.title || '新标签页'}</span>
            </button>
            {tab.active ? (
              <button
                aria-label="关闭标签页"
                className="paw-browser-tab-close"
                onClick={() => onClose(tab.id)}
                type="button"
              >
                <X size={12} />
              </button>
            ) : null}
          </div>
        ))}
        <button
          aria-label="新建标签页"
          className="paw-browser-new-tab"
          disabled={newTabDisabled}
          onClick={onNewTab}
          type="button"
        >
          <Plus size={14} />
        </button>
      </div>
    </div>
  );
}

function BrowserTabIcon({ tab }: { tab: BrowserTabItem }) {
  return (
    <span aria-hidden="true" className="paw-browser-tab-icon">
      {tab.loading ? (
        <LoaderCircle className="ui-spin" size={13} />
      ) : tab.failed ? (
        <CircleAlert size={13} />
      ) : tab.favicon ? (
        <img alt="" src={tab.favicon} />
      ) : (
        <Globe2 size={13} />
      )}
    </span>
  );
}
