import { describe, expect, it } from 'vitest';
import { settleTraceOptimizationCommand, traceOptimizationCommandId } from './optimization-command';

describe('Trace optimization command identity', () => {
  it('reuses an uncertain action identity until an authoritative result settles it', () => {
    const key = 'report:1:candidate:1:install';
    const first = traceOptimizationCommandId(key);
    expect(traceOptimizationCommandId(key)).toBe(first);
    expect(traceOptimizationCommandId('report:1:candidate:1:keep_original')).not.toBe(first);
    settleTraceOptimizationCommand(key);
    expect(traceOptimizationCommandId(key)).not.toBe(first);
    settleTraceOptimizationCommand(key);
    settleTraceOptimizationCommand('report:1:candidate:1:keep_original');
  });
});
