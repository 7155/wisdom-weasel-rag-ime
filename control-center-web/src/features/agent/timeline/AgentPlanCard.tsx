import { CheckCircle2, Circle, ListChecks, LoaderCircle } from 'lucide-react';
import type { AgentPlanProjection } from '@/contracts/agent-reducer';

export function AgentPlanCard({ plan }: { plan: AgentPlanProjection }) {
  if (plan.items.length === 0) return null;
  const activeIndex = plan.items.findIndex((item) => item.status === 'in_progress');
  const allCompleted = plan.counts.completed === plan.counts.total;
  const state = allCompleted ? 'completed' : activeIndex >= 0 ? 'running' : 'pending';
  const progress = plan.counts.total > 0
    ? Math.round((plan.counts.completed / plan.counts.total) * 100)
    : 0;
  const progressLabel = allCompleted
    ? `${plan.counts.total} / ${plan.counts.total} 项已完成`
    : activeIndex >= 0
      ? `第 ${activeIndex + 1} / ${plan.counts.total} 步 · ${plan.counts.completed} 项已完成`
      : `等待下一步 · ${plan.counts.completed} / ${plan.counts.total} 项已完成`;

  return (
    <section
      aria-label="会话执行计划"
      aria-live="polite"
      className="agent-plan-card"
      data-state={state}
    >
      <header>
        <span aria-hidden="true"><ListChecks size={16} /></span>
        <strong>执行计划</strong>
        <small>{allCompleted ? '已完成' : activeIndex >= 0 ? '进行中' : '待开始'}</small>
      </header>
      <ol>
        {plan.items.map((item) => (
          <li
            aria-current={item.status === 'in_progress' ? 'step' : undefined}
            data-state={item.status}
            key={item.id}
          >
            <span aria-hidden="true" className="agent-plan-card__state">
              {item.status === 'completed'
                ? <CheckCircle2 size={17} />
                : item.status === 'in_progress'
                  ? <LoaderCircle size={17} />
                  : <Circle size={17} />}
            </span>
            <span className="agent-plan-card__label">{item.title}</span>
          </li>
        ))}
      </ol>
      <footer>
        <div className="agent-plan-card__progress-copy">
          <span>{progressLabel}</span>
          <strong>{progress}%</strong>
        </div>
        <div
          aria-label={`计划完成度 ${progress}%`}
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={progress}
          role="progressbar"
        >
          <i style={{ width: `${progress}%` }} />
        </div>
      </footer>
    </section>
  );
}
