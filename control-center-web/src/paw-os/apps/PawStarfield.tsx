/**
 * 星空 v2 — immersive fullscreen celestial visualization.
 *
 * Three sibling skies over one shared shell:
 * - PawSessionStarfield — the Session as a planet, real subagent runs as
 *   moons (`agent.subagents.list`);
 * - PawRoomStarfield — the Room as a solar system of partner planets and
 *   real handoff light beams. Sol is the facilitator's star: it is drawn only
 *   while a coordinator actually hosts the Room, otherwise the sky stays a
 *   partner-only constellation around an empty origin;
 * - PawGalaxyStarfield — every Room one star system in a small galaxy.
 *
 * The work leads: every body carries the task it is running, live handoff
 * beams name the WorkItem in flight, and bodies with no live work go quiet
 * so the backdrop and the settled planets never outshout them.
 *
 * The shell renders a fullscreen WebGL stage (three.js) with an information
 * feed, an honest motion legend and a detail card for any picked body. When
 * WebGL is unavailable or lost it falls back to a fullscreen 2D sky that
 * reads the same motion profiles, so movement semantics never change:
 * fast orbit/spin = genuinely running; still or slow drift = idle/settled;
 * queue, review and failure are rings and light, never fake motion.
 *
 * Exit is disposal: unmounting tears down the WebGL stage (Starfield3D's
 * cleanup calls StarfieldStage.dispose) and the shell releases any system
 * fullscreen it itself acquired, leaving no listener, loop or context behind.
 */

import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  Box,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Orbit,
  Sparkles,
  TriangleAlert,
  X,
} from 'lucide-react';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { useControlTransport } from '@/app/control-transport';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import {
  hasActiveSubagentRuns,
  subagentRuns,
} from '@/features/agent/status/subagent-data';
import { subagentFailurePolicy } from '@/features/agent/status/subagent-presentation';
import type { RoomSummary } from '@/features/rooms/room-types';
import { usePageVisibility } from '@/platform/use-page-visibility';
import type { RoomFocusProjection } from './room-focus-projection';
import { roomFocusStateLabel } from './room-focus-projection';
import {
  buildGalaxyStarfield,
  buildRoomStarfield,
  buildSessionStarfield,
  starfieldHash,
  STARFIELD_VIEWBOX,
} from './starfield-projection';
import { Starfield3D, useReducedMotion, webglAvailable } from './starfield/Starfield3D';
import {
  buildRoomFeed,
  buildSessionFeed,
  feedTimeLabel,
  type StarfieldFeedItem,
} from './starfield/starfield-feed';
import {
  buildGalaxySceneModel,
  buildRoomSceneModel,
  buildSessionSceneModel,
  liveBeamLinks,
  SCENE_STAGE_RADIUS,
  sceneBodyAriaLabel,
  type SceneMode,
  type StarfieldSceneModel,
} from './starfield/starfield-scene-model';

/* ------------------------------------------------------------------ */
/* Small shared hooks                                                  */
/* ------------------------------------------------------------------ */

function useNowMs(): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return nowMs;
}

/* ------------------------------------------------------------------ */
/* Deterministic 2D star backdrop (fallback stage)                     */
/* ------------------------------------------------------------------ */

interface BackdropStar {
  x: number;
  y: number;
  r: number;
  opacity: number;
  delayS: number;
  tint: string;
}

interface BackdropMeteor {
  xPct: number;
  yPct: number;
  angleDeg: number;
  delayS: number;
  durationS: number;
  lengthPx: number;
}

/** Deterministic LCG stream seeded by a string — same seed, same sky. */
function seededStream(seed: string): () => number {
  let state = starfieldHash(seed) || 1;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

/* A believable night sky is not monochrome: mostly ice-white stars, a band
 * of hot blue ones, a few warm giants and a rare violet outlier. */
const STAR_TINTS = ['#e9efff', '#bdd5ff', '#ffe2b8', '#ddc9ff'] as const;

function starTint(roll: number): string {
  if (roll < 0.56) return STAR_TINTS[0];
  if (roll < 0.82) return STAR_TINTS[1];
  if (roll < 0.95) return STAR_TINTS[2];
  return STAR_TINTS[3];
}

function starLayers(seed: string): Record<'far' | 'mid' | 'near', BackdropStar[]> {
  const next = seededStream(seed);
  const layer = (count: number, rMin: number, rMax: number, oMin: number, oMax: number) =>
    Array.from({ length: count }, () => ({
      x: Math.round(next() * STARFIELD_VIEWBOX),
      y: Math.round(next() * STARFIELD_VIEWBOX),
      r: Math.round((rMin + next() * (rMax - rMin)) * 100) / 100,
      opacity: Math.round((oMin + next() * (oMax - oMin)) * 100) / 100,
      delayS: Math.round(next() * 620) / 100,
      tint: starTint(next()),
    }));
  return {
    far: layer(90, 0.5, 1.1, 0.18, 0.5),
    mid: layer(48, 0.8, 1.7, 0.28, 0.68),
    near: layer(20, 1.3, 2.4, 0.5, 0.95),
  };
}

/** Occasional shooting stars: pure seeded decoration, never a work signal. */
function meteorShower(seed: string): BackdropMeteor[] {
  const next = seededStream(`${seed}:meteors`);
  return Array.from({ length: 3 }, (_, index) => ({
    xPct: Math.round((6 + next() * 58) * 10) / 10,
    yPct: Math.round((5 + next() * 36) * 10) / 10,
    angleDeg: Math.round(16 + next() * 30),
    delayS: Math.round((index * 6.4 + next() * 5.2) * 10) / 10,
    durationS: Math.round((15 + next() * 9) * 10) / 10,
    lengthPx: Math.round(86 + next() * 74),
  }));
}

function StarfieldBackdrop2D({ seed }: { seed: string }) {
  const layers = useMemo(() => starLayers(seed), [seed]);
  const meteors = useMemo(() => meteorShower(seed), [seed]);
  return (
    <>
      <svg
        aria-hidden="true"
        className="paw-sf2__stars"
        preserveAspectRatio="xMidYMid slice"
        viewBox={`0 0 ${STARFIELD_VIEWBOX} ${STARFIELD_VIEWBOX}`}
      >
        {(['far', 'mid', 'near'] as const).map((name) => (
          <g className="paw-sf2__star-layer" data-layer={name} key={name}>
            {layers[name].map((star, index) => (
              <circle
                cx={star.x}
                cy={star.y}
                key={`${name}-${index}`}
                opacity={star.opacity}
                r={star.r}
                style={{ animationDelay: `${star.delayS}s`, fill: star.tint }}
              />
            ))}
          </g>
        ))}
      </svg>
      <div aria-hidden="true" className="paw-sf2__meteors">
        {meteors.map((meteor, index) => (
          <i
            className="paw-sf2__meteor"
            key={index}
            style={{
              '--sf-meteor-x': `${meteor.xPct}%`,
              '--sf-meteor-y': `${meteor.yPct}%`,
              '--sf-meteor-angle': `${meteor.angleDeg}deg`,
              '--sf-meteor-delay': `${meteor.delayS}s`,
              '--sf-meteor-duration': `${meteor.durationS}s`,
              '--sf-meteor-length': `${meteor.lengthPx}px`,
            } as CSSProperties}
          />
        ))}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* 2D fallback stage — same scene model, same motion semantics         */
/* ------------------------------------------------------------------ */

function Starfield2D({
  model,
  selectedId,
  onPick,
}: {
  model: StarfieldSceneModel;
  selectedId: string | null;
  onPick: (bodyId: string | null) => void;
}) {
  // Session moons genuinely orbit (CSS rotation, period from real motion);
  // Room planets hold position so handoff beams stay attached — a comet of
  // light sweeps the orbit of a genuinely working planet instead.
  const orbiting = model.mode === 'session';
  const radiusPct = (radius: number) => (radius / SCENE_STAGE_RADIUS) * 44;
  const viewboxPoint = (radius: number, phaseRad: number) => ({
    x: 500 + radiusPct(radius) * 10 * Math.cos(phaseRad),
    y: 500 + radiusPct(radius) * 10 * Math.sin(phaseRad),
  });
  const pointById = new Map(model.bodies.map((body) => [
    body.id,
    viewboxPoint(body.orbitRadius, body.phaseRad),
  ]));
  const namedBeamIds = new Set(liveBeamLinks(model).map((link) => link.id));

  return (
    <div className="paw-sf2" data-mode={model.mode}>
      <StarfieldBackdrop2D seed={model.seed} />
      <div aria-hidden="true" className="paw-sf2__nebula" />
      <div aria-hidden="true" className="paw-sf2__aurora" />
      {model.mode === 'galaxy' ? <div aria-hidden="true" className="paw-sf2__swirl" /> : null}
      <div className="paw-sf2__stage">
        <svg
          aria-hidden="true"
          className="paw-sf2__chart"
          viewBox={`0 0 ${STARFIELD_VIEWBOX} ${STARFIELD_VIEWBOX}`}
        >
          {model.ringRadii.map((radius) => (
            <circle className="paw-sf2__ring" cx={500} cy={500} key={radius} r={radiusPct(radius) * 10} />
          ))}
          {!orbiting ? model.bodies.filter((body) => body.motion.working).map((body) => (
            <circle
              className="paw-sf2__ring-comet"
              cx={500}
              cy={500}
              key={`comet:${body.id}`}
              pathLength={100}
              r={radiusPct(body.orbitRadius) * 10}
              style={{ '--sf-ring-angle': `${(body.phaseRad * 180) / Math.PI}deg` } as CSSProperties}
            />
          )) : null}
          <g className="paw-sf2__beams">
            {model.links.map((link) => {
              // Without Sol there is no origin to leave from: a handoff whose
              // source is not on stage simply is not drawn.
              const from = pointById.get(link.fromId) ?? (model.center ? { x: 500, y: 500 } : undefined);
              const to = pointById.get(link.toId);
              if (!from || !to) return null;
              const named = namedBeamIds.has(link.id);
              return (
                <g
                  className="paw-sf2__beam"
                  data-failed={link.failed || undefined}
                  data-live={link.live || undefined}
                  key={link.id}
                >
                  <line pathLength={link.live ? 100 : undefined} x1={from.x} x2={to.x} y1={from.y} y2={to.y} />
                  {link.live ? (
                    <circle
                      className="paw-sf2__packet"
                      r={6}
                      style={{ offsetPath: `path('M ${from.x} ${from.y} L ${to.x} ${to.y}')` } as CSSProperties}
                    >
                      <title>{link.label}</title>
                    </circle>
                  ) : null}
                  {named ? (
                    <text
                      className="paw-sf2__beam-label"
                      x={(from.x + to.x) / 2}
                      y={(from.y + to.y) / 2 - 8}
                    >
                      {link.label}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </g>
        </svg>
        {model.bodies.map((body) => {
          const angleDeg = (body.phaseRad * 180) / Math.PI;
          const periodS = body.motion.orbitRadPerS > 0
            ? Math.round((Math.PI * 2) / (body.motion.orbitRadPerS * body.speedFactor))
            : 0;
          const point = pointById.get(body.id)!;
          const label = (
            <>
              <i aria-hidden="true" className="paw-sf2__body" data-kind={body.kind} />
              <span className="paw-sf2__body-label">
                <strong>{body.title}</strong>
                <small>{body.subtitle}</small>
                {body.task && !body.idle ? <em>{body.task}</em> : null}
              </span>
            </>
          );
          return orbiting ? (
            <div
              className="paw-sf2__orbiter"
              data-working={body.motion.working || undefined}
              key={body.id}
              style={{
                '--sf-angle': `${angleDeg}deg`,
                '--sf-radius': `${radiusPct(body.orbitRadius)}%`,
                '--sf-period': `${periodS || 60}s`,
              } as CSSProperties}
            >
              <button
                aria-label={sceneBodyAriaLabel(model.mode, body)}
                className="paw-sf2__body-button"
                data-idle={body.idle || undefined}
                data-ring={body.motion.ring === 'none' ? undefined : body.motion.ring}
                data-selected={selectedId === body.id || undefined}
                data-tone={body.motion.tone}
                data-working={body.motion.working || undefined}
                onClick={() => onPick(body.id)}
                title={body.detail || undefined}
                type="button"
              >
                {label}
              </button>
            </div>
          ) : (
            <button
              aria-label={sceneBodyAriaLabel(model.mode, body)}
              className="paw-sf2__body-button paw-sf2__body-button--fixed"
              data-idle={body.idle || undefined}
              data-kind={body.kind}
              data-ring={body.motion.ring === 'none' ? undefined : body.motion.ring}
              data-selected={selectedId === body.id || undefined}
              data-tone={body.motion.tone}
              data-working={body.motion.working || undefined}
              key={body.id}
              onClick={() => onPick(body.id)}
              style={{ left: `${point.x / 10}%`, top: `${point.y / 10}%` }}
              title={body.detail || undefined}
              type="button"
            >
              {label}
            </button>
          );
        })}
        {model.center ? (
          <button
            aria-label={`${model.center.title} · ${model.center.subtitle}`}
            className="paw-sf2__center"
            data-kind={model.center.kind}
            data-selected={selectedId === 'center' || undefined}
            data-tone={model.center.motion.tone}
            data-working={model.center.motion.working || undefined}
            onClick={() => onPick('center')}
            type="button"
          >
            <i aria-hidden="true" className="paw-sf2__center-glow" />
            <i aria-hidden="true" className="paw-sf2__center-body" />
            {model.center.kind === 'planet' ? <i aria-hidden="true" className="paw-sf2__center-ring" /> : null}
            <span className="paw-sf2__body-label paw-sf2__body-label--center">
              <strong>{model.center.title}</strong>
              <small>{model.center.subtitle}</small>
            </span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Immersive shell: stage + topbar + feed + legend + detail card       */
/* ------------------------------------------------------------------ */

function StarfieldShell({
  ariaLabel,
  mode,
  immersive,
  onExit,
  exitLabel,
  onEnterImmersive,
  sceneModel,
  feed,
  nowMs,
  legend,
  legendLabel,
  status,
  renderDetail,
  active = true,
}: {
  ariaLabel: string;
  mode: SceneMode;
  immersive: boolean;
  onExit?: () => void;
  exitLabel?: string;
  onEnterImmersive?: () => void;
  sceneModel: StarfieldSceneModel;
  feed: StarfieldFeedItem[];
  nowMs: number;
  legend: ReactNode;
  legendLabel: string;
  status?: ReactNode;
  renderDetail: (bodyId: string) => ReactNode | null;
  active?: boolean;
}) {
  const rootRef = useRef<HTMLElement | null>(null);
  const pageVisible = usePageVisibility();
  const reducedMotion = useReducedMotion();
  const webglOk = useMemo(() => webglAvailable(), []);
  const [renderMode, setRenderMode] = useState<'3d' | '2d'>(() => (webglOk ? '3d' : '2d'));
  const [fellBack, setFellBack] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selectedId;
  const [feedOpen, setFeedOpen] = useState(true);
  const [browserFullscreen, setBrowserFullscreen] = useState(false);

  // A body that left the sky cannot stay selected.
  useEffect(() => {
    if (!selectedId || selectedId === 'center') return;
    if (!sceneModel.bodies.some((body) => body.id === selectedId)) setSelectedId(null);
  }, [sceneModel, selectedId]);

  // ESC: first close the detail card, then leave the sky.
  useEffect(() => {
    if (!immersive) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (document.fullscreenElement) return;
      if (selectedRef.current) {
        setSelectedId(null);
      } else {
        onExit?.();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [immersive, onExit]);

  // Fullscreen ownership is tracked by containment, so the sky only ever
  // manages a fullscreen session it started itself.
  const ownsFullscreenRef = useRef(false);
  useEffect(() => {
    const onChange = () => {
      const element = document.fullscreenElement;
      const root = rootRef.current;
      const owned = Boolean(element && root && (element === root || root.contains(element)));
      ownsFullscreenRef.current = owned;
      setBrowserFullscreen(owned);
    };
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  // Dispose on exit: leaving the sky releases the system fullscreen it took,
  // otherwise the user would be stranded fullscreen with the controls gone.
  useEffect(() => () => {
    if (
      ownsFullscreenRef.current
      && document.fullscreenElement
      && typeof document.exitFullscreen === 'function'
    ) {
      void document.exitFullscreen().catch(() => undefined);
    }
  }, []);

  const fullscreenApiAvailable = immersive
    && typeof document.documentElement.requestFullscreen === 'function';
  const toggleBrowserFullscreen = () => {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => undefined);
    } else {
      void rootRef.current?.requestFullscreen().catch(() => undefined);
    }
  };

  const detail = selectedId ? renderDetail(selectedId) : null;

  const content = (
    <section
      aria-label={ariaLabel}
      className="paw-sf"
      data-immersive={immersive || undefined}
      data-mode={mode}
      data-reduced-motion={reducedMotion || undefined}
      data-render={renderMode}
      ref={rootRef}
      role="region"
    >
      {renderMode === '3d' ? (
        <Starfield3D
          model={sceneModel}
          onFallback={() => {
            setRenderMode('2d');
            setFellBack(true);
          }}
          onPick={setSelectedId}
          running={active && pageVisible}
          selectedId={selectedId}
        />
      ) : (
        <Starfield2D model={sceneModel} onPick={setSelectedId} selectedId={selectedId} />
      )}

      <header className="paw-sf__topbar">
        <div className="paw-sf__topbar-side">
          {immersive && onExit ? (
            <button className="paw-sf__exit" onClick={onExit} type="button">
              <ArrowLeft size={14} />
              <span>{exitLabel ?? '退出星空'}</span>
              <kbd>Esc</kbd>
            </button>
          ) : null}
          {!immersive && onEnterImmersive ? (
            <button className="paw-sf__exit" onClick={onEnterImmersive} type="button">
              <Maximize2 size={14} />
              <span>全屏星空</span>
            </button>
          ) : null}
        </div>
        <div className="paw-sf__topbar-side">
          {fellBack ? <span className="paw-sf__notice">3D 不可用，已切换为平面星空</span> : null}
          {webglOk ? (
            <button
              aria-label={renderMode === '3d' ? '切换为平面星空' : '切换为 3D 星空'}
              className="paw-sf__mode-toggle"
              onClick={() => setRenderMode((value) => (value === '3d' ? '2d' : '3d'))}
              type="button"
            >
              <Box size={14} />
              <span>{renderMode === '3d' ? '2D' : '3D'}</span>
            </button>
          ) : null}
          {fullscreenApiAvailable ? (
            <button
              aria-label={browserFullscreen ? '退出系统全屏' : '进入系统全屏'}
              className="paw-sf__mode-toggle"
              onClick={toggleBrowserFullscreen}
              type="button"
            >
              {browserFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
          ) : null}
        </div>
      </header>

      {feed.length ? (
        <aside aria-label="星空信息流" className="paw-sf__feed" data-open={feedOpen || undefined}>
          <button
            aria-expanded={feedOpen}
            className="paw-sf__feed-toggle"
            onClick={() => setFeedOpen((value) => !value)}
            type="button"
          >
            <Sparkles size={13} />
            <span>动态</span>
          </button>
          {feedOpen ? (
            <ol className="paw-sf__feed-list">
              {feed.map((item) => (
                <li key={item.id}>
                  <button
                    className="paw-sf__feed-item"
                    data-tone={item.tone}
                    onClick={item.bodyId ? () => setSelectedId(item.bodyId ?? null) : undefined}
                    type="button"
                  >
                    <i aria-hidden="true" />
                    <span className="paw-sf__feed-text">
                      <strong>{item.actor}</strong>
                      <span>{item.text}</span>
                    </span>
                    <span className="paw-sf__feed-meta">
                      {item.stateLabel} · {feedTimeLabel(item.atMs, nowMs)}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          ) : null}
        </aside>
      ) : null}

      {status}

      <footer aria-label={legendLabel} className="paw-sf__hud">
        {legend}
        <span className="paw-sf__hint">转动 = 正在工作 · 停驻 = 空闲或已完成</span>
      </footer>

      {detail ? (
        <aside aria-label="天体详情" className="paw-sf__card">
          <button
            aria-label="关闭详情"
            className="paw-sf__card-close"
            onClick={() => setSelectedId(null)}
            type="button"
          >
            <X size={14} />
          </button>
          {detail}
        </aside>
      ) : null}
    </section>
  );

  return immersive ? createPortal(content, document.body) : content;
}

/* ------------------------------------------------------------------ */
/* Session: planet + subagent moons                                    */
/* ------------------------------------------------------------------ */

export function PawSessionStarfield({
  active,
  busy,
  sessionId,
  sessionTitle,
  immersive = true,
  onExit,
  onOpenRun,
  onOpenWorkbench,
}: {
  /** Only an active sky polls the run graph. */
  active: boolean;
  busy: boolean;
  sessionId: string;
  sessionTitle: string;
  immersive?: boolean;
  onExit?: () => void;
  onOpenRun?: (run: AgentSubagentRunV1) => void;
  onOpenWorkbench?: () => void;
}) {
  const transport = useControlTransport();
  const pageVisible = usePageVisibility();
  const nowMs = useNowMs();
  const runsQuery = useQuery({
    queryKey: ['paw-starfield', 'session-subagents', sessionId],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.subagents.list',
      query: { sessionId, limit: 50 },
      signal,
    }),
    enabled: active && pageVisible && Boolean(sessionId),
    refetchInterval: active && pageVisible
      ? (query) => hasActiveSubagentRuns(subagentRuns(query.state.data)) ? 1_000 : 5_000
      : false,
    retry: false,
  });
  const runs = useMemo(() => subagentRuns(runsQuery.data), [runsQuery.data]);
  const runById = useMemo(() => new Map(runs.map((run) => [run.id, run])), [runs]);
  const model = useMemo(() => buildSessionStarfield(sessionId, runs), [runs, sessionId]);
  const sceneModel = useMemo(
    () => buildSessionSceneModel(model, { busy, sessionTitle }),
    [busy, model, sessionTitle],
  );
  const feed = useMemo(
    () => buildSessionFeed(runs, { busy, sessionTitle, nowMs }),
    [busy, nowMs, runs, sessionTitle],
  );
  const empty = !runsQuery.isPending && !runsQuery.error && model.moons.length === 0;

  const renderDetail = (bodyId: string): ReactNode | null => {
    if (bodyId === 'center') {
      return (
        <>
          <header className="paw-sf__card-head">
            <strong>{sessionTitle}</strong>
            <span data-tone={busy ? 'working' : 'muted'}>{busy ? '正在执行' : '待命'}</span>
          </header>
          <p className="paw-sf__card-task">
            这颗主星是当前 Session。周围每颗卫星都是一次真实的子 Agent 运行。
          </p>
          <dl className="paw-sf__card-rows">
            <div><dt>卫星</dt><dd>运行 {model.counts.active} · 返回 {model.counts.returned} · 待处理 {model.counts.attention}</dd></div>
          </dl>
        </>
      );
    }
    const run = runById.get(bodyId);
    const moon = model.moons.find((candidate) => candidate.runId === bodyId);
    if (!run || !moon) return null;
    const failurePolicy = subagentFailurePolicy(run);
    return (
      <>
        <header className="paw-sf__card-head">
          <strong>{moon.templateLabel}</strong>
          <span data-tone={moon.attention ? 'attention' : moon.active ? 'working' : 'done'}>{moon.stateLabel}</span>
        </header>
        <p className="paw-sf__card-task">{moon.task || '未公开任务说明'}</p>
        <dl className="paw-sf__card-rows">
          <div><dt>上下文</dt><dd>{moon.contextMode === 'fork' ? '延续主对话' : '独立上下文'}</dd></div>
          <div><dt>用量</dt><dd>{run.usage.turnCount} 轮 · {run.usage.toolCount} 次工具 · {run.usage.totalTokens.toLocaleString()} tokens</dd></div>
          {run.error ? <div><dt>错误</dt><dd>{run.error}</dd></div> : null}
        </dl>
        {failurePolicy ? <p className="paw-sf__card-note">{failurePolicy}</p> : null}
        <div className="paw-sf__card-actions">
          {onOpenRun ? (
            <button onClick={() => onOpenRun(run)} type="button">打开运行详情</button>
          ) : null}
          {onOpenWorkbench ? (
            <button onClick={onOpenWorkbench} type="button">子 Agent 工作台</button>
          ) : null}
        </div>
      </>
    );
  };

  return (
    <StarfieldShell
      active={active}
      ariaLabel="Session 星空"
      exitLabel="返回对话"
      feed={feed}
      immersive={immersive}
      legend={(
        <>
          <span data-tone="working"><i aria-hidden="true" />运行 {model.counts.active}</span>
          <span data-tone="done"><i aria-hidden="true" />返回 {model.counts.returned}</span>
          <span data-tone="attention"><i aria-hidden="true" />待处理 {model.counts.attention}</span>
          {onOpenWorkbench ? (
            <button onClick={onOpenWorkbench} type="button"><Orbit size={13} />子 Agent 工作台</button>
          ) : null}
        </>
      )}
      legendLabel="星空图例"
      mode="session"
      nowMs={nowMs}
      renderDetail={renderDetail}
      sceneModel={sceneModel}
      status={(
        <>
          {runsQuery.isPending && active ? (
            <div className="paw-sf__status">
              <LoaderCircle className="ui-spin" size={15} />
              <span>正在同步子 Agent 运行图</span>
            </div>
          ) : null}
          {runsQuery.error ? (
            <div className="paw-sf__status" role="alert">
              <TriangleAlert size={15} />
              <span>运行图暂时无法读取</span>
              <button onClick={() => void runsQuery.refetch()} type="button">重新读取</button>
            </div>
          ) : null}
          {empty ? (
            <div className="paw-sf__status">
              <Sparkles size={15} />
              <span>这颗行星还没有卫星；启动子 Agent 后会出现在轨道上。</span>
            </div>
          ) : null}
        </>
      )}
      {...(onExit ? { onExit } : {})}
    />
  );
}

/* ------------------------------------------------------------------ */
/* Room: the whole solar system                                        */
/* ------------------------------------------------------------------ */

/** The card names the work a partner owns; the Room App owns the full list. */
const ROOM_CARD_WORK_LIMIT = 4;

export function PawRoomStarfield({
  focus,
  roomId,
  immersive = true,
  onExit,
  onOpenParticipant,
}: {
  focus: RoomFocusProjection;
  roomId: string;
  immersive?: boolean;
  onExit?: () => void;
  onOpenParticipant?: (participantId: string) => void;
}) {
  const nowMs = useNowMs();
  const model = useMemo(() => buildRoomStarfield(focus), [focus]);
  const sceneModel = useMemo(() => buildRoomSceneModel(model, roomId), [model, roomId]);
  // Sol belongs to the facilitator. With nobody hosting, the scene model
  // returns no center and the sky stays a partner-only constellation.
  const hosted = sceneModel.center !== null;
  const feed = useMemo(() => buildRoomFeed(focus, { hosted }), [focus, hosted]);

  const renderDetail = (bodyId: string): ReactNode | null => {
    if (bodyId === 'center') {
      if (!model.hasCoordinator) return null;
      return (
        <>
          <header className="paw-sf__card-head">
            <strong>Sol · {model.goal.title}</strong>
            <span data-tone={model.goal.state === 'running' ? 'working' : model.goal.state === 'blocked' || model.goal.state === 'failed' ? 'attention' : 'done'}>
              {model.goal.stateLabel}
            </span>
          </header>
          <p className="paw-sf__card-task">整个太阳系围绕这个 Room 目标运转。</p>
          <dl className="paw-sf__card-rows">
            <div><dt>工作项</dt><dd>进行 {model.counts.active} · 复核 {model.counts.review} · 受阻 {model.counts.blocked} · 完成 {model.counts.completed}</dd></div>
          </dl>
        </>
      );
    }
    const planet = model.planets.find((candidate) => candidate.participantId === bodyId);
    if (!planet) return null;
    const partner = focus.partners.find((candidate) => candidate.participantId === bodyId);
    // The planet's real work, straight from the Room WorkItems it owns.
    const ownedWork = focus.workItems
      .filter((item) => partner?.ownedWorkItemIds.includes(item.id))
      .slice(0, ROOM_CARD_WORK_LIMIT);
    return (
      <>
        <header className="paw-sf__card-head">
          <strong>{planet.celestialName}</strong>
          <span data-tone={planet.attention ? 'attention' : planet.state === 'running' ? 'working' : 'done'}>{planet.stateLabel}</span>
        </header>
        <p className="paw-sf__card-task">{planet.currentAction}</p>
        {ownedWork.length ? (
          <ul aria-label="负责的工作项" className="paw-sf__card-work">
            {ownedWork.map((item) => (
              <li key={item.id}>
                <strong>{item.objective}</strong>
                <small>{roomFocusStateLabel(item.state)}{item.blocker ? ` · ${item.blocker.reason}` : ''}</small>
              </li>
            ))}
          </ul>
        ) : null}
        <dl className="paw-sf__card-rows">
          {planet.collaborationRole ? <div><dt>职责</dt><dd>{planet.collaborationRole}</dd></div> : null}
          <div><dt>负责工作项</dt><dd>{planet.ownedWorkCount} 项</dd></div>
          {partner?.latestReceipt ? <div><dt>最近回执</dt><dd>{partner.latestReceipt}</dd></div> : null}
        </dl>
        {onOpenParticipant ? (
          <div className="paw-sf__card-actions">
            <button onClick={() => onOpenParticipant(planet.participantId)} type="button">打开伙伴窗口</button>
          </div>
        ) : null}
      </>
    );
  };

  return (
    <StarfieldShell
      ariaLabel="Room 星空"
      exitLabel="返回 Room"
      feed={feed}
      immersive={immersive}
      legend={(
        <>
          <span data-tone="working"><i aria-hidden="true" />进行 {model.counts.active}</span>
          <span data-tone="review"><i aria-hidden="true" />复核 {model.counts.review}</span>
          <span data-tone="attention"><i aria-hidden="true" />受阻 {model.counts.blocked}</span>
          <span data-tone="done"><i aria-hidden="true" />完成 {model.counts.completed}</span>
          <span data-tone={model.goal.state === 'running' ? 'working' : 'muted'}>
            <i aria-hidden="true" />目标 · {model.goal.stateLabel}
          </span>
        </>
      )}
      legendLabel={model.hasCoordinator ? 'Sol 星空图例' : 'Room 星空图例'}
      mode="room"
      nowMs={nowMs}
      renderDetail={renderDetail}
      sceneModel={sceneModel}
      status={hosted ? undefined : (
        <div className="paw-sf__status">
          <Orbit size={15} />
          <span>这间 Room 没有主持人，中心不画 Sol；伙伴星按各自的工作项排列。</span>
        </div>
      )}
      {...(onExit ? { onExit } : {})}
    />
  );
}

/* ------------------------------------------------------------------ */
/* Many Rooms: a small galaxy                                          */
/* ------------------------------------------------------------------ */

export function PawGalaxyStarfield({
  rooms,
  onOpenRoom,
}: {
  rooms: readonly RoomSummary[];
  onOpenRoom: (roomId: string) => void;
}) {
  const nowMs = useNowMs();
  const [immersive, setImmersive] = useState(false);
  const model = useMemo(() => buildGalaxyStarfield(rooms), [rooms]);
  const sceneModel = useMemo(() => buildGalaxySceneModel(model), [model]);
  if (!model.systems.length) return null;

  const renderDetail = (bodyId: string): ReactNode | null => {
    const system = model.systems.find((candidate) => candidate.roomId === bodyId);
    if (!system) return null;
    return (
      <>
        <header className="paw-sf__card-head">
          <strong>{system.title}</strong>
          <span data-tone={system.active ? 'working' : 'muted'}>{system.active ? '活跃' : '已归档'}</span>
        </header>
        <dl className="paw-sf__card-rows">
          <div><dt>伙伴</dt><dd>{system.participantCount} 位</dd></div>
          <div><dt>最近更新</dt><dd>{feedTimeLabel(system.updatedAtMs, nowMs)}</dd></div>
        </dl>
        <div className="paw-sf__card-actions">
          <button onClick={() => onOpenRoom(system.roomId)} type="button">进入 Room</button>
        </div>
      </>
    );
  };

  return (
    <StarfieldShell
      ariaLabel="Room 星系"
      exitLabel="返回工作台"
      feed={[]}
      immersive={immersive}
      legend={(
        <span><i aria-hidden="true" />共 {model.totalRooms} 个 Room · 每颗恒星是一间真实 Room</span>
      )}
      legendLabel="星系图例"
      mode="galaxy"
      nowMs={nowMs}
      onEnterImmersive={() => setImmersive(true)}
      onExit={() => setImmersive(false)}
      renderDetail={renderDetail}
      sceneModel={sceneModel}
    />
  );
}
