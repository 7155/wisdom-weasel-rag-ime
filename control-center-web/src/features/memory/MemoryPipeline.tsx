import {
  Archive,
  ArrowRight,
  BookOpen,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Tags,
} from 'lucide-react';
import { Button } from '@/components/primitives';
import { asRecord, numberValue, stringValue } from '@/features/overview/management-ui';

type MemoryLayer = 'evidence' | 'atoms' | 'books';
type MemoryPipelineState = 'ready' | 'pending' | 'error';

interface MemoryPipelineProps {
  /** The catalog layer that currently owns the workspace, or '' outside the catalog. */
  activeLayer: MemoryLayer | '';
  organizeActive: boolean;
  onOpenLayer: (layer: MemoryLayer) => void;
  onOpenOrganize: () => void;
  onRetry: () => void;
  summary: Record<string, unknown>;
  summaryState: MemoryPipelineState;
}

/**
 * The Memory App's spine: the governed pipeline 来源 -> 整理 -> 记忆 -> 主题,
 * always visible with live counts and flow state. Every stage is a real
 * navigation target; the connectors carry the actual quantity waiting to move
 * to the next stage, so "what happens to my data" is legible without opening
 * a status page.
 */
export function MemoryPipeline({
  activeLayer,
  onOpenLayer,
  onOpenOrganize,
  onRetry,
  organizeActive,
  summary,
  summaryState,
}: MemoryPipelineProps) {
  const projection = asRecord(summary.projection);
  const timelineCounts = asRecord(summary.activityTimelineCounts);
  const governanceCounts = asRecord(summary.governanceProposalCounts);
  const latestTimeline = asRecord(summary.latestActivityTimeline);
  const ownerCuration = asRecord(summary.ownerCuration);
  const evidenceCount = numberValue(
    summary.memoryEvidenceCount,
    numberValue(summary.evidenceSourceCount) + numberValue(summary.agentEvidenceCount),
  );
  const agentCapturedEvidenceCount = numberValue(
    summary.agentCapturedEvidenceCount,
    numberValue(summary.agentEvidenceCount),
  );
  const currentAtomCount = numberValue(
    summary.currentAtomCount,
    numberValue(summary.memoryAtomCount),
  );
  const historicalAtomCount = numberValue(
    summary.historicalAtomCount,
    numberValue(summary.memoryAtomArchivedCount),
  );
  const atomTotalCount = numberValue(
    summary.memoryAtomTotalCount,
    currentAtomCount
      + historicalAtomCount
      + numberValue(summary.memoryAtomSourceArchiveCount),
  );
  const pendingSourceCount = numberValue(
    summary.ownerCurationPendingSourceCount,
    numberValue(ownerCuration.pendingSourceCount, numberValue(summary.pendingCompileEvents)),
  );
  const pendingGovernance = numberValue(summary.needsReviewSourceCount)
    + numberValue(governanceCounts.preview)
    + numberValue(timelineCounts.draft);
  const projectionSignal = describeProjection(projection);
  const caughtUp = summaryState === 'ready' && pendingSourceCount === 0;

  return (
    <section aria-label="记忆整理链路" className="memory-pipeline" data-state={summaryState}>
      <ol aria-label="记忆内容分类" className="memory-pipeline__stages">
        <PipelineStage
          active={activeLayer === 'evidence'}
          ariaLabel={`来源 · 来源记录 · ${evidenceCount} 项`}
          code="来源"
          count={evidenceCount}
          detail={`输入法 ${numberValue(summary.inputMethodEvidenceCount)} · 语音 ${numberValue(summary.voiceEvidenceCount)} · 伙伴主动记录 ${agentCapturedEvidenceCount}`}
          icon={Archive}
          index="01"
          label="来源记录"
          onClick={() => onOpenLayer('evidence')}
          stage="evidence"
          state={summaryState}
        />
        <PipelineFlow
          label={caughtUp ? '暂无待整理' : `待整理 ${pendingSourceCount}`}
          tone={caughtUp ? 'idle' : 'active'}
        />
        <PipelineStage
          active={organizeActive}
          ariaLabel={`整理 · ${caughtUp ? '已到今天' : `${pendingSourceCount} 条等待处理`}`}
          code="整理"
          count={pendingSourceCount}
          detail={caughtUp ? '已到今天 · 新输入出现后继续' : '分批处理，形成草案后等你审核'}
          icon={Sparkles}
          index="02"
          label="分批审核"
          onClick={onOpenOrganize}
          stage="organize"
          state={summaryState}
          unit="条"
        />
        <PipelineFlow label="审核后写入" tone="idle" />
        <PipelineStage
          active={activeLayer === 'atoms'}
          ariaLabel={`记忆 · 已整理记忆 · ${currentAtomCount} 项`}
          code="记忆"
          count={currentAtomCount}
          detail={`全部 ${atomTotalCount} · 历史 ${historicalAtomCount}`}
          icon={Tags}
          index="03"
          label="已整理记忆"
          onClick={() => onOpenLayer('atoms')}
          stage="atoms"
          state={summaryState}
        />
        <PipelineFlow label="按主题归类" tone="idle" />
        <PipelineStage
          active={activeLayer === 'books'}
          ariaLabel={`主题 · 长期主题 · ${numberValue(summary.memoryBookCount)} 项`}
          code="主题"
          count={numberValue(summary.memoryBookCount)}
          detail="按主题持续查找"
          icon={BookOpen}
          index="04"
          label="长期主题"
          onClick={() => onOpenLayer('books')}
          stage="books"
          state={summaryState}
        />
      </ol>
      <div className="memory-pipeline__meta">
        {summaryState === 'error' ? (
          <div className="memory-pipeline__fault" role="status">
            <span>记忆状态读取失败，计数暂不可用。</span>
            <Button leadingIcon={<RefreshCw size={13} />} onClick={onRetry} size="small" variant="quiet">重试</Button>
          </div>
        ) : (
          <div aria-label="记忆整理状态" className="memory-pipeline__signals">
            <PipelineSignal detail={projectionSignal.detail} label="检索索引" tone={projectionSignal.tone} />
            <PipelineSignal
              detail={pendingGovernance ? `${pendingGovernance} 项等待处理` : '没有待处理草案'}
              label="待确认"
              tone={pendingGovernance ? 'warning' : 'success'}
            />
            <PipelineSignal
              detail={latestTimelineStatus(latestTimeline)}
              label="最近整理"
              tone={stringValue(latestTimeline.status) === 'draft' ? 'warning' : 'info'}
            />
          </div>
        )}
        <p className="memory-pipeline__note">
          <ShieldCheck aria-hidden="true" size={14} />
          <span>主题不会替代原始记录；每条结论都能沿这条链路回到来源。</span>
        </p>
      </div>
    </section>
  );
}

function PipelineStage({
  active,
  ariaLabel,
  code,
  count,
  detail,
  icon: Icon,
  index,
  label,
  onClick,
  stage,
  state,
  unit = '项',
}: {
  active: boolean;
  ariaLabel: string;
  code: string;
  count: number;
  detail: string;
  icon: typeof Archive;
  index: string;
  label: string;
  onClick: () => void;
  stage: 'evidence' | 'organize' | 'atoms' | 'books';
  state: MemoryPipelineState;
  unit?: string;
}) {
  return (
    <li className="memory-pipeline__stage" data-active={active || undefined} data-stage={stage}>
      <button aria-current={active ? 'step' : undefined} aria-label={ariaLabel} onClick={onClick} type="button">
        <span aria-hidden="true" className="memory-pipeline__stage-index">{index}</span>
        <span aria-hidden="true" className="memory-pipeline__stage-icon"><Icon size={15} /></span>
        <span className="memory-pipeline__stage-copy">
          <small>{label}</small>
          <strong>{code}</strong>
        </span>
        <span className="memory-pipeline__stage-count" data-unknown={state !== 'ready' || undefined}>
          {state === 'ready' ? count : '—'}
          <small>{unit}</small>
        </span>
        <em className="memory-pipeline__stage-detail">{state === 'error' ? '状态暂不可用' : detail}</em>
      </button>
    </li>
  );
}

function PipelineFlow({ label, tone }: { label: string; tone: 'active' | 'idle' }) {
  return (
    <li aria-hidden="true" className="memory-pipeline__flow" data-tone={tone}>
      <span>{label}</span>
      <ArrowRight size={13} />
    </li>
  );
}

function PipelineSignal({
  detail,
  label,
  tone,
}: {
  detail: string;
  label: string;
  tone: 'success' | 'warning' | 'info';
}) {
  return (
    <div className="memory-pipeline__signal" data-tone={tone}>
      <i aria-hidden="true" />
      <span><strong>{label}</strong><small>{detail}</small></span>
    </div>
  );
}

function latestTimelineStatus(value: Record<string, unknown>): string {
  const date = stringValue(value.date);
  if (!date) return '尚未生成';
  const status = ({
    draft: '待审核',
    approved: '已批准',
    rejected: '已驳回',
    superseded: '已更新',
  } as Record<string, string>)[stringValue(value.status)] ?? '已整理';
  return `${date.slice(5)} ${status}`;
}

function describeProjection(value: Record<string, unknown>): {
  detail: string;
  tone: 'success' | 'warning' | 'info';
} {
  if (!Object.keys(value).length) return { detail: '状态未知', tone: 'info' };
  if (value.fresh === true) {
    return { detail: `${numberValue(value.retrievalDocuments)} 份检索文档`, tone: 'success' };
  }
  if (value.projectionInitialized === false) return { detail: '尚未初始化', tone: 'warning' };
  const dead = numberValue(value.dead);
  if (dead) return { detail: `${dead} 项需要人工处理`, tone: 'warning' };
  const backlog = numberValue(value.backlog);
  if (backlog) return { detail: `${backlog} 项正在同步`, tone: 'warning' };
  return { detail: '等待重新校验', tone: 'warning' };
}
