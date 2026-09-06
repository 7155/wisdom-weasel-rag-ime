import { ArrowRight, Check } from 'lucide-react';
import { Button } from '@/components/primitives';
import { isActiveJob, isExperimentResult, type GoldenSuite } from './types';

export const goldenSteps = ['起草题目', '审核标准', '校准评审', '冻结与实验'];

export function goldenJourney(suite: GoldenSuite | null, unsaved = false) {
  const approved = suite?.cases.filter((item) => item.review.status === 'approved') ?? [];
  const pending = suite?.cases.filter((item) => item.review.status === 'pending').length ?? 0;
  const reviewed = approved.some((item) => item.split === 'development') && approved.some((item) => item.split === 'holdout');
  const calibrated = Boolean(suite?.calibration?.ready && suite.calibration.suiteRevision === suite.revision && !unsaved);
  const complete = Boolean(!unsaved && suite?.snapshot?.sourceRevision === suite?.revision && suite?.jobs.some((job) => job.kind === 'experiment' && job.state === 'completed'
    && isExperimentResult(job.result) && job.result.snapshotId === suite.snapshot?.snapshotId));
  const done = [Boolean(suite?.cases.length), reviewed && pending === 0 && !unsaved, calibrated, complete];
  const next = !suite?.cases.length ? 0 : !reviewed || pending || unsaved ? 1 : !calibrated ? 2 : 3;
  return { done, next, pending, approved: approved.length, complete };
}

export function WorkflowGuide({ suite, step, unsaved, onStep }: {
  suite: GoldenSuite | null; step: number; unsaved: boolean; onStep: (step: number) => void;
}) {
  const journey = goldenJourney(suite, unsaved);
  const running = suite?.jobs.find(isActiveJob);
  const messages = [
    suite ? ['来源已保存，接下来让 Agent 起草', `按这份资料生成 ${suite.targetCount} 道题及参考标准。起草会调用模型，之后由你逐题核对。`]
      : ['先提供一份能核对答案的资料', '文档、历史任务或失败记录都可以。接下来会依次生成题目、确认评分标准，再比较两个 Agent 方案。'],
    ['核对题目、必要事实和原文引用', '符合来源就保存通过；不符合就修改或拒绝。开发题用于调整，留出题保留到最后验证。'],
    ['给示例答案打分，再检查模型是否同意', '先按标准判断答案是否通过并保存标签，再运行评审校准。正确、错误、边界三类样例都要覆盖。'],
    journey.complete ? ['这轮实验已结束，先看留出题的表现', '比较通过率、逐题答案和费用来源，再决定是否继续调整。结论只覆盖本次题集。']
      : ['固定评分标准，然后比较两个方案', '基线是当前方案，候选是准备尝试的新方案。只在开发题调整，最后用留出题验证，结果会保存在这里。'],
  ];
  return <aside className="golden-guidance" aria-label="本步指引">
    <div><span className="golden-guidance__eyebrow">{journey.complete && step === 3 ? '本轮已完成' : `第 ${step + 1} 步 / 4`}</span>
      <h3>{messages[step][0]}</h3><p>{messages[step][1]}</p></div>
    {suite && !running && !unsaved && step !== journey.next ? <Button leadingIcon={<ArrowRight size={16} />} onClick={() => onStep(journey.next)}>前往{goldenSteps[journey.next]}</Button> : null}
  </aside>;
}

export function SavedProgress({ value, total, label }: { value: number; total: number; label: string }) {
  return <div className="golden-saved-progress" aria-label={label}>
    <span>{value === total && total > 0 ? <Check size={16} aria-hidden="true" /> : null}{label} <strong>{value} / {total}</strong></span>
    {total > 0 ? <progress value={value} max={total} aria-label={label} /> : null}
  </div>;
}
