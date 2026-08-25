import { Radio } from 'lucide-react';
import type { RouteDecisionPlanView } from './route-decision-plan';

/**
 * Visible dispatch plan for one route decision: target and reason up front,
 * then every candidate with its real weight bar and routing signals. Weights
 * come from the routing payload; the bar never animates to an invented value.
 * Reused by the Room lane for the same event rendered in the Room timeline.
 */
export function RouteDecisionPlan({ view }: { view: RouteDecisionPlanView }) {
  return (
    <section
      aria-label={`分派计划：${view.summary || view.policyLabel}`}
      className="agent-route-plan"
    >
      <header className="agent-route-plan__header">
        <Radio aria-hidden="true" size={14} />
        <strong>{view.targetName ? `分派给 ${view.targetName}` : view.policyLabel}</strong>
        {view.reasonLabel ? <span className="agent-route-plan__badge">{view.reasonLabel}</span> : null}
        {view.parallelLabel ? <span className="agent-route-plan__badge" data-tone="wave">{view.parallelLabel}</span> : null}
      </header>
      {view.phaseName || view.workItemLabel ? (
        <p className="agent-route-plan__phase">
          {[view.phaseName, view.workItemLabel].filter(Boolean).join(' · ')}
        </p>
      ) : null}
      {view.candidates.length ? (
        <ol aria-label="候选伙伴与权重" className="agent-route-plan__candidates">
          {view.candidates.map((candidate) => (
            <li data-selected={candidate.selected || undefined} key={candidate.id}>
              <strong>{candidate.name}</strong>
              <span
                aria-label={`权重 ${Math.round(candidate.score * 100)}%`}
                className="agent-route-plan__score"
                role="img"
              >
                <i style={{ transform: `scaleX(${candidate.score})` }} />
              </span>
              <small>
                {candidate.signalLabels.length
                  ? candidate.signalLabels.join('、')
                  : candidate.selected ? '入选' : '未入选'}
              </small>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
