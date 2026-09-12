import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StoryDeck } from './StoryDeck';

const experiment = {
  experimentId: 'exp-real-1', title: '企业知识库问答', status: 'kept', businessProblem: '验证答案证据链',
  dataset: { datasetId: 'frozen-dataset', split: 'validation', caseCount: 4 },
  scoring: { hardGates: ['citationResolution'] },
  factors: [{ name: 'prompt', before: 'v1', after: 'v2', reason: '补齐引用约束' }],
  baseline: { runId: 'run-base', metrics: { recall: 0.4, toolCalls: 6 }, evidenceRefs: ['runs/base.json'] },
  candidate: { runId: 'run-candidate', metrics: { recall: 0.8, toolCalls: 5 }, evidenceRefs: ['runs/candidate.json'] },
  comparison: { decision: 'keep', decisionReason: '质量提升且门禁通过' },
  claim: { allowed: 'Validation retrieval improvement', forbidden: '生产质量提升' },
} as never;

describe('StoryDeck', () => {
  it('renders the actual lab record fields and moves through result sections', () => {
    render(<StoryDeck experiments={[experiment]} selectedId="exp-real-1" onSelect={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: '第 2 页：证据' }));
    expect(screen.getByText(/Baseline：run-base/)).toBeInTheDocument();
    expect(screen.getByText(/Candidate：run-candidate/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '第 4 页：效果' }));
    expect(screen.getByText(/40% \(0\.4\)/)).toBeInTheDocument();
    expect(screen.getByText(/80% \(0\.8\)/)).toBeInTheDocument();
    expect(screen.getByText(/\+40% \(\+0\.4\)/)).toBeInTheDocument();
    expect(screen.getByText(/runs\/base\.json/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '第 5 页：边界' }));
    expect(screen.getByText('生产质量提升')).toBeInTheDocument();
  });
});
