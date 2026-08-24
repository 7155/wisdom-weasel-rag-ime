import { describe, expect, it } from 'vitest';
import type { RoomFocusState } from '../room-focus-projection';
import {
  galaxySystemMotion,
  IDLE_DRIFT_RAD_PER_S,
  roomBodyMotion,
  sessionCoreMotion,
  stilledMotion,
  subagentMotion,
  WORKING_ORBIT_RAD_PER_S,
  WORKING_SPIN_RAD_PER_S,
} from './starfield-motion';

describe('starfield motion semantics', () => {
  it('lets only a genuinely running subagent orbit and spin fast', () => {
    const running = subagentMotion('running', false);
    expect(running.working).toBe(true);
    expect(running.orbitRadPerS).toBe(WORKING_ORBIT_RAD_PER_S);
    expect(running.spinRadPerS).toBe(WORKING_SPIN_RAD_PER_S);
    expect(running.tone).toBe('working');

    for (const state of ['queued', 'completed', 'returned', 'failed', 'aborted', 'timed_out', 'contract_invalid'] as const) {
      const value = subagentMotion(state, state === 'contract_invalid');
      expect(value.working, state).toBe(false);
      expect(value.orbitRadPerS, state).toBeLessThanOrEqual(IDLE_DRIFT_RAD_PER_S);
      expect(value.spinRadPerS, state).toBe(0);
    }
  });

  it('tells queue, review and failure through rings and light, not fake motion', () => {
    expect(subagentMotion('queued', false)).toMatchObject({ ring: 'queued', tone: 'queued', orbitRadPerS: 0, pulseHz: 0 });
    expect(subagentMotion('returned', false)).toMatchObject({ ring: 'review', tone: 'review' });
    expect(subagentMotion('completed', false)).toMatchObject({ ring: 'none', tone: 'done', orbitRadPerS: IDLE_DRIFT_RAD_PER_S });
    expect(subagentMotion('aborted', false)).toMatchObject({ ring: 'none', tone: 'paused', orbitRadPerS: 0 });
    for (const state of ['failed', 'timed_out', 'contract_invalid'] as const) {
      const value = subagentMotion(state, false);
      expect(value.ring, state).toBe('attention');
      expect(value.tone, state).toBe('attention');
      expect(value.pulseHz, state).toBeGreaterThan(0);
      expect(value.orbitRadPerS, state).toBe(0);
    }
    // A contract-invalid flag forces attention even over a nominal state.
    expect(subagentMotion('completed', true).ring).toBe('attention');
  });

  it('moves a Room partner fast only in the running state', () => {
    const running = roomBodyMotion('running');
    expect(running.working).toBe(true);
    expect(running.orbitRadPerS).toBe(WORKING_ORBIT_RAD_PER_S);

    const nonRunning: RoomFocusState[] = ['idle', 'waiting', 'review', 'blocked', 'completed', 'failed', 'stopped', 'disconnected'];
    for (const state of nonRunning) {
      const value = roomBodyMotion(state);
      expect(value.working, state).toBe(false);
      expect(value.orbitRadPerS, state).toBeLessThanOrEqual(IDLE_DRIFT_RAD_PER_S);
      expect(value.spinRadPerS, state).toBe(0);
    }
    expect(roomBodyMotion('waiting').ring).toBe('queued');
    expect(roomBodyMotion('review').ring).toBe('review');
    expect(roomBodyMotion('blocked')).toMatchObject({ ring: 'attention', tone: 'attention' });
    expect(roomBodyMotion('failed')).toMatchObject({ ring: 'attention', tone: 'attention' });
    expect(roomBodyMotion('disconnected').tone).toBe('muted');
  });

  it('spins the Session core planet only while the Session is busy', () => {
    const busy = sessionCoreMotion(true);
    expect(busy.working).toBe(true);
    expect(busy.spinRadPerS).toBeGreaterThan(IDLE_DRIFT_RAD_PER_S);
    const idle = sessionCoreMotion(false);
    expect(idle.working).toBe(false);
    expect(idle.spinRadPerS).toBeLessThanOrEqual(IDLE_DRIFT_RAD_PER_S);
  });

  it('never grants a galaxy star fast motion just for being an active Room', () => {
    const active = galaxySystemMotion(true);
    expect(active.working).toBe(false);
    expect(active.orbitRadPerS).toBeLessThanOrEqual(IDLE_DRIFT_RAD_PER_S);
    const archived = galaxySystemMotion(false);
    expect(archived.orbitRadPerS).toBe(0);
    expect(archived.tone).toBe('muted');
  });

  it('stills every velocity under reduced motion while keeping ring and tone', () => {
    const stilled = stilledMotion(subagentMotion('running', false));
    expect(stilled).toMatchObject({ orbitRadPerS: 0, spinRadPerS: 0, pulseHz: 0, tone: 'working', working: true });
    const alert = stilledMotion(roomBodyMotion('blocked'));
    expect(alert).toMatchObject({ orbitRadPerS: 0, pulseHz: 0, ring: 'attention', tone: 'attention' });
  });
});
