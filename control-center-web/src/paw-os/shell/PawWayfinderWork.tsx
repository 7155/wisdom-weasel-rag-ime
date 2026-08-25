import { ChevronDown, ChevronRight, CircleAlert, LoaderCircle, Search, Users } from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { sessionItems } from '@/features/agent/types';
import { usePawDesktopApi, usePawDesktopStore } from '../runtime/desktop-context';
import {
  projectWayfinderWork,
  wayfinderWorkTime,
  type WayfinderWorkBucket,
  type WayfinderWorkItem,
  type WayfinderWorkRoomSource,
} from './wayfinder-work-projection';

/**
 * PawWayfinderWork — the desktop's recent-work panel, owned by the Wayfinder.
 *
 * Desktop density is the contract: the panel is one bounded surface whose
 * height never exceeds its reserved corner of the viewport; overflow lives in
 * an internal scroll area, and the projection itself (fold, dedupe, buckets)
 * keeps the first screen short. It reads the same directory the Agent App
 * owns, and every row opens straight into the Agent window — the desktop
 * projects work, it does not manage it.
 *
 * The panel takes no props, so memo makes it a true leaf: it re-renders when
 * its own directory read, query or expansion state changes, and never because
 * the desktop above it moved a window, drew a lasso or ticked the clock.
 */
export const PawWayfinderWork = memo(function PawWayfinderWork() {
  const transport = useControlTransport();
  const api = usePawDesktopApi();
  const desktopIdle = usePawDesktopStore((state) => Object.keys(state.windows).length === 0);
  const [sessions, setSessions] = useState<ReturnType<typeof sessionItems>>([]);
  const [rooms, setRooms] = useState<WayfinderWorkRoomSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [query, setQuery] = useState('');
  const [expandedBuckets, setExpandedBuckets] = useState<ReadonlySet<string>>(new Set());
  const [expandedRepeats, setExpandedRepeats] = useState<ReadonlySet<string>>(new Set());
  const listRef = useRef<HTMLDivElement>(null);
  const lastLoadRef = useRef(0);

  const load = useCallback(async () => {
    lastLoadRef.current = Date.now();
    setLoading(true);
    const [sessionResult, roomResult] = await Promise.allSettled([
      transport.request({ pathId: 'agent.sessions.list', query: { limit: 100 } }),
      transport.request({ pathId: 'agent.rooms.list', query: { limit: 100 } }),
    ]);
    if (sessionResult.status === 'fulfilled') setSessions(sessionItems(sessionResult.value));
    if (roomResult.status === 'fulfilled') setRooms(roomSources(roomResult.value));
    setFailed(sessionResult.status === 'rejected' && roomResult.status === 'rejected');
    setLoading(false);
    setLoadedOnce(true);
  }, [transport]);

  useEffect(() => { void load(); }, [load]);

  // Returning to an empty desktop is the moment the panel is actually read;
  // refresh then instead of polling while a window covers it.
  useEffect(() => {
    if (!desktopIdle || !loadedOnce) return;
    if (Date.now() - lastLoadRef.current < 5_000) return;
    void load();
  }, [desktopIdle, load, loadedOnce]);

  const view = useMemo(
    () => projectWayfinderWork({ nowMs: Date.now(), query, rooms, sessions }),
    [query, rooms, sessions],
  );
  const searching = query.trim().length > 0;

  const openItem = useCallback((kind: 'session' | 'room', id: string, title: string) => {
    const state = api.getState();
    state.openApp('agent', {
      entityId: id,
      initialRoute: `/agent?${kind === 'room' ? 'room' : 'session'}=${encodeURIComponent(id)}`,
      target: { kind, id, title },
      title: 'Agent',
    });
  }, [api]);

  // Same roving-arrow contract as the desktop shortcut column: focus walks the
  // rows without tabbing through every control on the desktop.
  const walkRows = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const host = listRef.current;
    if (!host) return;
    const rows = Array.from(host.querySelectorAll<HTMLButtonElement>('button[data-wayfinder-row]'));
    const current = rows.indexOf(document.activeElement as HTMLButtonElement);
    if (current === -1) return;
    event.preventDefault();
    const next = event.key === 'Home'
      ? 0
      : event.key === 'End'
      ? rows.length - 1
      : Math.min(Math.max(current + (event.key === 'ArrowDown' ? 1 : -1), 0), rows.length - 1);
    rows[next]?.focus();
  };

  const hasRows = view.rowCount > 0;
  return (
    <section aria-label="最近工作" className="paw-wayfinder-work" data-paw-desktop-panel>
      <header className="paw-wayfinder-work__head">
        <strong>最近工作</strong>
        {hasRows ? <span className="paw-wayfinder-work__count">{view.rowCount}</span> : null}
      </header>
      <label className="paw-wayfinder-work__search">
        <Search aria-hidden="true" size={13} />
        <input
          aria-label="搜索最近工作"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索"
          type="search"
          value={query}
        />
      </label>
      <div aria-busy={loading || undefined} className="paw-wayfinder-work__list" onKeyDown={walkRows} ref={listRef}>
        {loading && !loadedOnce ? (
          <p className="paw-wayfinder-work__state" role="status"><LoaderCircle className="paw-wayfinder-work__spin" size={13} />正在读取</p>
        ) : failed ? (
          <p className="paw-wayfinder-work__state" role="alert">
            <CircleAlert size={13} />工作记录暂时无法读取
            <button onClick={() => void load()} type="button">重试</button>
          </p>
        ) : !hasRows ? (
          <p className="paw-wayfinder-work__state">
            {searching ? '没有匹配的工作' : '还没有工作记录'}
            {searching ? null : (
              <button onClick={() => openAgentHome(api)} type="button">开始一件事</button>
            )}
          </p>
        ) : view.buckets.map((bucket) => (
          <WorkBucket
            bucket={bucket}
            expanded={searching || expandedBuckets.has(bucket.id)}
            expandedRepeats={expandedRepeats}
            key={bucket.id}
            onOpen={openItem}
            onToggle={() => setExpandedBuckets((current) => toggled(current, bucket.id))}
            onToggleRepeats={(key) => setExpandedRepeats((current) => toggled(current, key))}
            searching={searching}
          />
        ))}
      </div>
    </section>
  );
});

function WorkBucket({ bucket, expanded, expandedRepeats, onOpen, onToggle, onToggleRepeats, searching }: {
  bucket: WayfinderWorkBucket;
  expanded: boolean;
  expandedRepeats: ReadonlySet<string>;
  onOpen: (kind: 'session' | 'room', id: string, title: string) => void;
  onToggle: () => void;
  onToggleRepeats: (key: string) => void;
  searching: boolean;
}) {
  // 更早 rests fully collapsed; 今天/本周 preview a short slice and only then
  // offer the rest inside the panel's own scroll area.
  const restingCount = Math.min(bucket.previewCount, bucket.items.length);
  const visibleItems = expanded ? bucket.items : bucket.items.slice(0, restingCount);
  const hiddenCount = bucket.items.length - visibleItems.length;
  const collapsedWholeBucket = !searching && bucket.previewCount === 0;
  return (
    <section className="paw-wayfinder-work__bucket" data-bucket={bucket.id}>
      {collapsedWholeBucket ? (
        <button
          aria-expanded={expanded}
          className="paw-wayfinder-work__bucket-toggle"
          onClick={onToggle}
          type="button"
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span>{bucket.label}</span>
          <small>{bucket.items.length}</small>
        </button>
      ) : (
        <h3 className="paw-wayfinder-work__bucket-label">{bucket.label}<small>{bucket.items.length}</small></h3>
      )}
      {(!collapsedWholeBucket || expanded) ? visibleItems.map((item) => (
        <WorkRow
          expandedRepeats={expandedRepeats}
          item={item}
          key={item.key}
          onOpen={onOpen}
          onToggleRepeats={onToggleRepeats}
        />
      )) : null}
      {!collapsedWholeBucket && hiddenCount > 0 ? (
        <button className="paw-wayfinder-work__more" onClick={onToggle} type="button">
          还有 {hiddenCount} 段
        </button>
      ) : null}
    </section>
  );
}

function WorkRow({ expandedRepeats, item, onOpen, onToggleRepeats }: {
  expandedRepeats: ReadonlySet<string>;
  item: WayfinderWorkItem;
  onOpen: (kind: 'session' | 'room', id: string, title: string) => void;
  onToggleRepeats: (key: string) => void;
}) {
  const repeatsOpen = expandedRepeats.has(item.key);
  const meta = [item.project, wayfinderWorkTime(item.updatedAtMs, Date.now())].filter(Boolean).join(' · ');
  return (
    <div className="paw-wayfinder-work__row-shell">
      <button
        className="paw-wayfinder-work__row"
        data-activity={item.activity}
        data-kind={item.kind}
        data-wayfinder-row
        onClick={() => onOpen(item.kind, item.id, item.title)}
        title={`${item.title} · ${meta}`}
        type="button"
      >
        <i aria-hidden="true" className="paw-wayfinder-work__dot" />
        <span className="paw-wayfinder-work__copy">
          <strong>{item.title}</strong>
          <small>
            {item.kind === 'room' ? <Users aria-hidden="true" size={11} /> : null}
            {item.agents.length ? (
              <span aria-label={`${item.agents.length} 位伙伴`} className="paw-wayfinder-work__agents">
                {item.agents.slice(0, 4).map((agent) => <b key={agent}>{agent}</b>)}
                {item.agents.length > 4 ? <b>+{item.agents.length - 4}</b> : null}
              </span>
            ) : null}
            {meta ? <span>{meta}</span> : null}
          </small>
        </span>
      </button>
      {item.repeats.length ? (
        <button
          aria-expanded={repeatsOpen}
          aria-label={`同名工作还有 ${item.repeats.length} 段`}
          className="paw-wayfinder-work__repeats-toggle"
          onClick={() => onToggleRepeats(item.key)}
          title={`同名工作还有 ${item.repeats.length} 段`}
          type="button"
        >
          ×{item.repeats.length + 1}
        </button>
      ) : null}
      {repeatsOpen ? item.repeats.map((repeat) => (
        <button
          className="paw-wayfinder-work__repeat"
          data-wayfinder-row
          key={`${repeat.kind}:${repeat.id}`}
          onClick={() => onOpen(repeat.kind, repeat.id, item.title)}
          type="button"
        >
          <span>较早一段</span>
          <small>{wayfinderWorkTime(repeat.updatedAtMs, Date.now())}</small>
        </button>
      )) : null}
    </div>
  );
}

function openAgentHome(api: ReturnType<typeof usePawDesktopApi>): void {
  api.getState().openApp('agent', { title: 'Agent' });
}

function toggled(current: ReadonlySet<string>, key: string): ReadonlySet<string> {
  const next = new Set(current);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

function roomSources(value: unknown): WayfinderWorkRoomSource[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return [];
  const envelope = value as Record<string, unknown>;
  const source = Array.isArray(envelope.items) ? envelope.items : Array.isArray(envelope.rooms) ? envelope.rooms : [];
  return source.filter((item): item is WayfinderWorkRoomSource => {
    if (typeof item !== 'object' || item === null) return false;
    const room = item as Record<string, unknown>;
    return typeof room.id === 'string'
      && typeof room.title === 'string'
      && typeof room.updatedAtMs === 'number';
  });
}
