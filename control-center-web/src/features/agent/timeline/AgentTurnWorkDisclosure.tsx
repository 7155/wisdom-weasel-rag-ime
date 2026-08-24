import { Check, ChevronRight, CircleSlash, TriangleAlert } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from 'react';
import type { AgentTurnStatus } from '@/contracts/agent-reducer';
import {
  toggleDisclosureOnKeyPreservingAnchor,
  toggleDisclosurePreservingAnchor,
} from './disclosure-anchor';
import type {
  AgentTurnSequenceEntry,
  AgentTurnWorkItem,
  AgentTurnWorkModel,
} from './agent-turn-work-model';
import { SmoothDisclosureReveal } from './SmoothDisclosureReveal';

type PresentationSegment = {
  key: string;
  role: AgentTurnWorkItem['role'];
  entries: AgentTurnSequenceEntry[];
};

const expansionOverrides = new Map<string, boolean>();

export function AgentTurnWorkDisclosure({
  createdAtMs,
  model,
  renderEntry,
  sessionId,
  turnId,
  turnStatus,
  updatedAtMs,
}: {
  createdAtMs: number;
  model: AgentTurnWorkModel;
  renderEntry: (entry: AgentTurnSequenceEntry) => ReactNode;
  sessionId: string;
  turnId: string;
  turnStatus?: AgentTurnStatus;
  updatedAtMs: number;
}) {
  const disclosureKey = `${sessionId}:${turnId}`;
  const contentId = `agent-turn-work-${useId().replace(/:/g, '')}`;
  const rootRef = useRef<HTMLElement>(null);
  const userReadWorkRef = useRef(false);
  const previousCanCollapseRef = useRef(model.canCollapse);
  const [expanded, setExpanded] = useState(() => (
    model.canCollapse ? expansionOverrides.get(disclosureKey) ?? false : true
  ));
  const setExpandedPersisted = useCallback<Dispatch<SetStateAction<boolean>>>((next) => {
    setExpanded((current) => {
      const value = typeof next === 'function' ? next(current) : next;
      expansionOverrides.set(disclosureKey, value);
      return value;
    });
  }, [disclosureKey]);

  useEffect(() => {
    const wasCollapsible = previousCanCollapseRef.current;
    previousCanCollapseRef.current = model.canCollapse;
    if (!model.canCollapse) {
      setExpanded(true);
      return;
    }
    const persisted = expansionOverrides.get(disclosureKey);
    if (persisted !== undefined) {
      setExpanded(persisted);
      return;
    }
    if (!wasCollapsible) {
      const readingInside = rootRef.current?.contains(document.activeElement) || userReadWorkRef.current;
      if (readingInside) {
        expansionOverrides.set(disclosureKey, true);
        setExpanded(true);
      } else {
        setExpanded(false);
      }
    }
  }, [disclosureKey, model.canCollapse]);

  const shownExpanded = !model.canCollapse || expanded;
  const segments = groupPresentationItems(model.items);
  const stepCount = model.hiddenActivityCount + model.hiddenMessageCount;
  const elapsed = formatElapsed(Math.max(0, updatedAtMs - createdAtMs));
  const statusNote = turnStatus === 'failed' ? '未完成' : turnStatus === 'aborted' ? '已停止' : '';
  const StateIcon = turnStatus === 'failed'
    ? TriangleAlert
    : turnStatus === 'aborted'
      ? CircleSlash
      : Check;
  const detail = [
    model.toolCount ? `${model.toolCount} 个工具` : '',
    elapsed,
    statusNote,
  ].filter(Boolean).join(' · ');
  // Each collapsed work segment keeps its position inside the full segment
  // list, so aria-controls must use the same indexes as the rendered reveals.
  const workSegmentIds = segments
    .map((segment, index) => (segment.role === 'work' ? `${contentId}-${index}` : ''))
    .filter(Boolean)
    .join(' ');

  return (
    <section
      className="agent-turn-sequence agent-turn-work"
      data-collapsible={model.canCollapse || undefined}
      data-expanded={shownExpanded || undefined}
      data-status={turnStatus}
      onPointerDownCapture={() => { if (!model.canCollapse) userReadWorkRef.current = true; }}
      onWheelCapture={() => { if (!model.canCollapse) userReadWorkRef.current = true; }}
      ref={rootRef}
    >
      {model.canCollapse ? (
        <button
          aria-controls={workSegmentIds}
          aria-expanded={shownExpanded}
          aria-label={`${shownExpanded ? '收起' : '展开'} ${stepCount} 个步骤${detail ? `，${detail}` : ''}`}
          className="agent-turn-work__toggle"
          data-status={turnStatus}
          onClick={(event) => toggleDisclosurePreservingAnchor(event, setExpandedPersisted)}
          onKeyDown={(event) => toggleDisclosureOnKeyPreservingAnchor(event, setExpandedPersisted)}
          type="button"
        >
          <span aria-hidden="true" className="agent-turn-work__state"><StateIcon size={12} /></span>
          <span className="agent-turn-work__copy"><strong>{stepCount} 个步骤</strong>{detail ? <small>{detail}</small> : null}</span>
          <ChevronRight aria-hidden="true" className="agent-turn-work__chevron" size={15} />
        </button>
      ) : null}
      <div className="agent-turn-work__sequence">
        {segments.map((segment, index) => segment.role === 'result' ? (
          <div className="agent-turn-work__result" data-turn-layer="result" key={segment.key}>
            {segment.entries.map((entry) => renderEntry(entry))}
          </div>
        ) : (
          <SmoothDisclosureReveal
            className="agent-turn-work__reveal"
            id={`${contentId}-${index}`}
            key={segment.key}
            open={shownExpanded}
          >
            <div
              aria-label="本轮步骤"
              className="agent-turn-work__process"
              data-turn-layer="work"
              role="tree"
            >
              {segment.entries.map((entry) => entry.kind === 'message' ? (
                <div
                  aria-level={1}
                  className="agent-turn-work__step agent-turn-work__step--message"
                  data-step-kind="message"
                  key={entryKey(entry)}
                  role="treeitem"
                >
                  <span aria-hidden="true" className="agent-turn-work__rail-dot" />
                  <div className="agent-turn-work__step-body">{renderEntry(entry)}</div>
                </div>
              ) : renderEntry(entry))}
            </div>
          </SmoothDisclosureReveal>
        ))}
      </div>
    </section>
  );
}

function groupPresentationItems(items: AgentTurnWorkItem[]): PresentationSegment[] {
  const segments: PresentationSegment[] = [];
  for (const item of items) {
    const previous = segments[segments.length - 1];
    if (previous?.role === item.role) {
      previous.entries.push(item.entry);
    } else {
      segments.push({
        key: `${item.role}:${entryKey(item.entry)}`,
        role: item.role,
        entries: [item.entry],
      });
    }
  }
  return segments;
}

function entryKey(entry: AgentTurnSequenceEntry): string {
  return entry.kind === 'message' ? entry.message.id : entry.key;
}

function formatElapsed(durationMs: number): string {
  if (durationMs < 1_000) return '';
  if (durationMs < 60_000) return `${Math.max(1, Math.round(durationMs / 1_000))} 秒`;
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.round((durationMs % 60_000) / 1_000);
  return seconds ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分`;
}

/** Test-only reset; production identity remains the stable Session/Turn key. */
export function resetAgentTurnDisclosureOverrides(): void {
  expansionOverrides.clear();
}
