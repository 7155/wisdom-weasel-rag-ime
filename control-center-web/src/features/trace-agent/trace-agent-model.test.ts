import { describe, expect, it } from 'vitest';

import {
  TRACE_AGENT_MAX_TARGETS,
  traceTargetColorToken,
  traceTargetKey,
  toggleTraceTargetSelection,
} from './trace-agent-model';

describe('Trace Agent target model', () => {
  it('uses a stable kind/id key and a deterministic display color', () => {
    expect(traceTargetKey('session', 'session:one')).toBe('session:session:one');
    expect(traceTargetColorToken('session:session:one')).toBe(
      traceTargetColorToken('session:session:one'),
    );
    expect(traceTargetColorToken('session:session:one')).not.toBe(
      traceTargetColorToken('session:session:two'),
    );
  });

  it('bounds selection at twelve and keeps toggling idempotent', () => {
    const full = Array.from({ length: TRACE_AGENT_MAX_TARGETS }, (_, index) => `session:${index}`);
    expect(toggleTraceTargetSelection(full, 'session:12')).toEqual(full);
    expect(toggleTraceTargetSelection(full, 'session:11')).toHaveLength(11);
    expect(toggleTraceTargetSelection([], 'session:one')).toEqual(['session:one']);
    expect(toggleTraceTargetSelection(['session:one'], 'session:one')).toEqual([]);
  });
});
