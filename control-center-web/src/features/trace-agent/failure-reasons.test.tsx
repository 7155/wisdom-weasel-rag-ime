import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  FAILURE_REASON_CATEGORIES,
  TraceFailureReasonPanel,
  classifyFailureReason,
} from './failure-reasons';

describe('TraceFailureReasonPanel', () => {
  it('keeps the nine authoritative categories visible and marks absent evidence unavailable', () => {
    render(
      <TraceFailureReasonPanel
        evidence={[{
          id: 'trace:1',
          source: 'Trace · trace:1',
          status: 'failed',
          title: 'write/edit validation error',
          summary: 'resourceRevision must match the current SHA-256 revision',
          createdAtMs: 1,
        }]}
        loading={false}
      />,
    );

    expect(FAILURE_REASON_CATEGORIES).toHaveLength(9);
    expect(screen.getByRole('region', { name: '失败原因分类' })).toBeInTheDocument();
    expect(screen.getByTestId('trace-failure-category-parameter_schema')).toHaveTextContent('已发现 · 1 条证据');
    expect(screen.getByTestId('trace-failure-category-security_policy')).toHaveTextContent('unavailable');
    expect(screen.getByText('resourceRevision must match the current SHA-256 revision')).toBeInTheDocument();
  });

  it('does not force an unrecognised public reason into a misleading category', () => {
    expect(classifyFailureReason({
      id: 'unknown',
      source: 'Session transcript · unknown',
      status: 'failed',
      title: '任务失败',
      summary: '失败原因未提供公开细节',
      createdAtMs: 1,
    })).toBeNull();
  });

  it('prefers authoritative failure codes over ambiguous prose', () => {
    expect(classifyFailureReason({
      id: 'model-refusal',
      source: 'Trace · trace:model-refusal',
      status: 'failed',
      title: '审核模型拒绝',
      summary: '请求未继续。',
      code: 'provider_model_refusal',
      createdAtMs: 1,
    })).toBe('model_rejection');
    expect(classifyFailureReason({
      id: 'memory-active-turn',
      source: 'Trace · trace:memory',
      status: 'failed',
      title: '记忆整理内部 Session',
      summary: 'Session already has an active turn',
      createdAtMs: 2,
    })).toBe('runtime_network');
  });
});
