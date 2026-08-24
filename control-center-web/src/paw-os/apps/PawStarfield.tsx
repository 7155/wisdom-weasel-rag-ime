/**
 * 星空 (starfield) visualization surfaces.
 *
 * Three sibling skies sharing one PAWOS celestial language:
 * - PawSessionStarfield — the current Session as a planet, its real subagent
 *   runs as moons on real orbits (`agent.subagents.list`);
 * - PawRoomStarfield — the whole Room as a solar system around Sol, partner
 *   planets clickable, real handoffs travelling as light beams;
 * - PawGalaxyStarfield — every Room a star system inside one small galaxy.
 *
 * All motion is projection-driven: only truly running bodies orbit or pulse,
 * and `prefers-reduced-motion` stills the entire sky. Celestial names remain
 * display aliases; clicks always carry the real Runtime identity.
 */

import { useQuery } from '@tanstack/react-query';
import { LoaderCircle, Orbit, Sparkles, TriangleAlert } from 'lucide-react';
import { useMemo, type CSSProperties } from 'react';
import { useControlTransport } from '@/app/control-transport';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import {
  hasActiveSubagentRuns,
  subagentRuns,
} from '@/features/agent/status/subagent-data';
import type { RoomSummary } from '@/features/rooms/room-types';
import { usePageVisibility } from '@/platform/use-page-visibility';
import {
  buildGalaxyStarfield,
  buildRoomStarfield,
  buildSessionStarfield,
  starfieldHash,
  STARFIELD_VIEWBOX,
} from './starfield-projection';
import type { RoomFocusProjection } from './room-focus-projection';

const CENTER = STARFIELD_VIEWBOX / 2;

/* ------------------------------------------------------------------ */
/* Shared deterministic star backdrop                                  */
/* ------------------------------------------------------------------ */

interface BackdropStar {
  x: number;
  y: number;
  r: number;
  opacity: number;
  delayS: number;
}

function starLayers(seed: string): Record<'far' | 'mid' | 'near', BackdropStar[]> {
  let state = starfieldHash(seed) || 1;
  const next = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
  const layer = (count: number, rMin: number, rMax: number, oMin: number, oMax: number) =>
    Array.from({ length: count }, () => ({
      x: Math.round(next() * STARFIELD_VIEWBOX),
      y: Math.round(next() * STARFIELD_VIEWBOX),
      r: Math.round((rMin + next() * (rMax - rMin)) * 100) / 100,
      opacity: Math.round((oMin + next() * (oMax - oMin)) * 100) / 100,
      delayS: Math.round(next() * 620) / 100,
    }));
  return {
    far: layer(72, 0.5, 1.1, 0.18, 0.5),
    mid: layer(40, 0.8, 1.7, 0.28, 0.68),
    near: layer(16, 1.3, 2.4, 0.5, 0.95),
  };
}

function PawStarfieldBackdrop({ seed }: { seed: string }) {
  const layers = useMemo(() => starLayers(seed), [seed]);
  return (
    <svg
      aria-hidden="true"
      className="paw-starfield__stars"
      preserveAspectRatio="xMidYMid slice"
      viewBox={`0 0 ${STARFIELD_VIEWBOX} ${STARFIELD_VIEWBOX}`}
    >
      {(['far', 'mid', 'near'] as const).map((name) => (
        <g className="paw-starfield__star-layer" data-layer={name} key={name}>
          {layers[name].map((star, index) => (
            <circle
              cx={star.x}
              cy={star.y}
              key={`${name}-${index}`}
              opacity={star.opacity}
              r={star.r}
              style={{ animationDelay: `${star.delayS}s` }}
            />
          ))}
        </g>
      ))}
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/* Session: planet + subagent moons                                    */
/* ------------------------------------------------------------------ */

export function PawSessionStarfield({
  active,
  busy,
  sessionId,
  sessionTitle,
  onOpenRun,
  onOpenWorkbench,
}: {
  /** Only an active sky polls the run graph. */
  active: boolean;
  busy: boolean;
  sessionId: string;
  sessionTitle: string;
  onOpenRun?: (run: AgentSubagentRunV1) => void;
  onOpenWorkbench?: () => void;
}) {
  const transport = useControlTransport();
  const pageVisible = usePageVisibility();
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
  const empty = !runsQuery.isPending && !runsQuery.error && model.moons.length === 0;

  return (
    <section
      aria-label="Session 星空"
      className="paw-starfield paw-starfield--session"
      data-busy={busy || undefined}
    >
      <PawStarfieldBackdrop seed={sessionId} />
      <div aria-hidden="true" className="paw-starfield__nebula" />
      <div className="paw-starfield__stage">
        <svg
          aria-hidden="true"
          className="paw-starfield__chart"
          viewBox={`0 0 ${STARFIELD_VIEWBOX} ${STARFIELD_VIEWBOX}`}
        >
          {model.ringRadii.map((radius) => (
            <circle className="paw-starfield__ring" cx={CENTER} cy={CENTER} key={radius} r={radius} />
          ))}
        </svg>
        {model.moons.map((moon) => {
          const run = runById.get(moon.runId);
          return (
            <div
              className="paw-starfield__orbiter"
              data-active={moon.active || undefined}
              key={moon.runId}
              style={{
                '--paw-orbit-angle': `${moon.orbit.angleDeg}deg`,
                '--paw-orbit-radius': `${moon.orbit.radius / 10}%`,
                '--paw-orbit-period': `${moon.orbit.periodS}s`,
              } as CSSProperties}
            >
              <button
                aria-label={`${moon.templateLabel} 卫星 · ${moon.task || '未公开任务说明'} · ${moon.stateLabel}`}
                className="paw-starfield__moon"
                data-attention={moon.attention || undefined}
                data-context={moon.contextMode}
                data-state={moon.state}
                onClick={run && onOpenRun ? () => onOpenRun(run) : undefined}
                title={moon.task || undefined}
                type="button"
              >
                <i aria-hidden="true" className="paw-starfield__moon-body" />
                <span className="paw-starfield__body-label">
                  <strong>{moon.templateLabel}</strong>
                  <small>{moon.stateLabel}</small>
                </span>
              </button>
            </div>
          );
        })}
        <div className="paw-starfield__core" data-state={busy ? 'busy' : 'idle'}>
          <i aria-hidden="true" className="paw-starfield__core-glow" />
          <i aria-hidden="true" className="paw-starfield__core-body" />
          <i aria-hidden="true" className="paw-starfield__core-ring" />
          <span className="paw-starfield__body-label paw-starfield__body-label--center">
            <strong>{sessionTitle}</strong>
            <small>{busy ? '正在执行' : 'Session 主星'}</small>
          </span>
        </div>
      </div>

      {runsQuery.isPending && active ? (
        <div className="paw-starfield__status">
          <LoaderCircle className="ui-spin" size={15} />
          <span>正在同步子 Agent 运行图</span>
        </div>
      ) : null}
      {runsQuery.error ? (
        <div className="paw-starfield__status" role="alert">
          <TriangleAlert size={15} />
          <span>运行图暂时无法读取</span>
          <button onClick={() => void runsQuery.refetch()} type="button">重新读取</button>
        </div>
      ) : null}
      {empty ? (
        <div className="paw-starfield__status">
          <Sparkles size={15} />
          <span>这颗行星还没有卫星；启动子 Agent 后会出现在轨道上。</span>
        </div>
      ) : null}

      <footer aria-label="星空图例" className="paw-starfield__hud">
        <span data-tone="active"><i aria-hidden="true" />运行 {model.counts.active}</span>
        <span data-tone="returned"><i aria-hidden="true" />返回 {model.counts.returned}</span>
        <span data-tone="attention"><i aria-hidden="true" />待处理 {model.counts.attention}</span>
        {onOpenWorkbench ? (
          <button onClick={onOpenWorkbench} type="button"><Orbit size={13} />子 Agent 工作台</button>
        ) : null}
      </footer>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Room: the whole solar system                                        */
/* ------------------------------------------------------------------ */

export function PawRoomStarfield({
  focus,
  roomId,
  onOpenParticipant,
}: {
  focus: RoomFocusProjection;
  roomId: string;
  onOpenParticipant?: (participantId: string) => void;
}) {
  const model = useMemo(() => buildRoomStarfield(focus), [focus]);
  return (
    <section
      aria-label="Room 星空"
      className="paw-starfield paw-starfield--room"
      data-goal-state={model.goal.state}
    >
      <PawStarfieldBackdrop seed={roomId} />
      <div aria-hidden="true" className="paw-starfield__nebula" />
      <div className="paw-starfield__stage">
        <svg
          aria-hidden="true"
          className="paw-starfield__chart"
          viewBox={`0 0 ${STARFIELD_VIEWBOX} ${STARFIELD_VIEWBOX}`}
        >
          {model.planets.map((planet) => (
            <g data-active={planet.active || undefined} key={`orbit:${planet.participantId}`}>
              <circle className="paw-starfield__ring" cx={CENTER} cy={CENTER} r={planet.radius} />
              {planet.active ? (
                <circle
                  className="paw-starfield__ring-comet"
                  cx={CENTER}
                  cy={CENTER}
                  pathLength={100}
                  r={planet.radius}
                  style={{ '--paw-ring-angle': `${planet.angleDeg}deg` } as CSSProperties}
                />
              ) : null}
            </g>
          ))}
          <g className="paw-starfield__beams">
            {model.beams.map((beam) => (
              <g
                className="paw-starfield__beam"
                data-live={beam.live || undefined}
                data-state={beam.state}
                key={beam.id}
              >
                <line pathLength={beam.live ? 100 : undefined} x1={beam.x1} x2={beam.x2} y1={beam.y1} y2={beam.y2} />
                {beam.live ? (
                  <circle
                    className="paw-starfield__packet"
                    r={6}
                    style={{ offsetPath: `path('M ${beam.x1} ${beam.y1} L ${beam.x2} ${beam.y2}')` } as CSSProperties}
                  >
                    <title>{beam.label}</title>
                  </circle>
                ) : null}
              </g>
            ))}
          </g>
        </svg>
        {model.planets.map((planet) => (
          <button
            aria-label={`${planet.celestialName}，${planet.displayName}，${planet.stateLabel}`}
            className="paw-starfield__planet"
            data-active={planet.active || undefined}
            data-attention={planet.attention || undefined}
            data-orbit={planet.orbitIndex % 4}
            data-state={planet.state}
            key={planet.participantId}
            onClick={onOpenParticipant ? () => onOpenParticipant(planet.participantId) : undefined}
            style={{ left: `${planet.x / 10}%`, top: `${planet.y / 10}%` }}
            title={planet.currentAction || undefined}
            type="button"
          >
            <i aria-hidden="true" className="paw-starfield__planet-body" />
            <span className="paw-starfield__body-label">
              <strong>{planet.celestialName}</strong>
              <small>{planet.displayName} · {planet.stateLabel}</small>
            </span>
          </button>
        ))}
        <div className="paw-starfield__sol" data-state={model.goal.state}>
          <i aria-hidden="true" className="paw-starfield__sol-corona" />
          <i aria-hidden="true" className="paw-starfield__sol-flare" />
          <i aria-hidden="true" className="paw-starfield__sol-body" />
          <span className="paw-starfield__body-label paw-starfield__body-label--center">
            <strong>Sol</strong>
            <small>{model.goal.title}</small>
          </span>
        </div>
      </div>

      <footer aria-label="Sol 星空图例" className="paw-starfield__hud">
        <span data-tone="active"><i aria-hidden="true" />进行 {model.counts.active}</span>
        <span data-tone="review"><i aria-hidden="true" />复核 {model.counts.review}</span>
        <span data-tone="attention"><i aria-hidden="true" />受阻 {model.counts.blocked}</span>
        <span data-tone="completed"><i aria-hidden="true" />完成 {model.counts.completed}</span>
        <span className="paw-starfield__hud-goal" data-state={model.goal.state}>
          <i aria-hidden="true" />{model.goal.stateLabel}
        </span>
      </footer>
    </section>
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
  const model = useMemo(() => buildGalaxyStarfield(rooms), [rooms]);
  if (!model.systems.length) return null;
  return (
    <section aria-label="Room 星系" className="paw-starfield paw-starfield--galaxy">
      <PawStarfieldBackdrop seed={model.systems.map((system) => system.roomId).join('|')} />
      <div aria-hidden="true" className="paw-starfield__swirl" />
      <div className="paw-starfield__stage">
        {model.systems.map((system) => (
          <button
            aria-label={`打开 Room ${system.title} · ${system.participantCount} 位伙伴 · ${system.active ? '活跃' : '已归档'}`}
            className="paw-starfield__system"
            data-active={system.active || undefined}
            data-hue={system.hueIndex}
            key={system.roomId}
            onClick={() => onOpenRoom(system.roomId)}
            style={{
              left: `${system.x / 10}%`,
              top: `${system.y / 10}%`,
              '--paw-system-scale': system.scale,
            } as CSSProperties}
            type="button"
          >
            <i aria-hidden="true" className="paw-starfield__system-star" />
            <span aria-hidden="true" className="paw-starfield__system-orbits">
              {Array.from({ length: Math.min(system.participantCount, 5) }, (_, slot) => (
                <i data-slot={slot} key={slot} />
              ))}
            </span>
            <span className="paw-starfield__body-label">
              <strong>{system.title}</strong>
              <small>{system.participantCount} 位伙伴</small>
            </span>
          </button>
        ))}
      </div>
      <footer aria-label="星系图例" className="paw-starfield__hud">
        <span><i aria-hidden="true" />共 {model.totalRooms} 个 Room · 每颗恒星是一间真实 Room</span>
      </footer>
    </section>
  );
}
