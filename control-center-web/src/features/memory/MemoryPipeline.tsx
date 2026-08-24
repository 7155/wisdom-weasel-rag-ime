import {
  Archive,
  ArrowRight,
  BookOpen,
  CalendarClock,
  Network,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Tags,
} from 'lucide-react';
import { Button } from '@/components/primitives';
import { useProductIdentity } from '@/features/identity/product-identity';
import { asRecord, numberValue, stringValue } from '@/features/overview/management-ui';

type MemoryLayer = 'evidence' | 'atoms' | 'books';

interface MemoryPipelineProps {
  activeLayer: MemoryLayer;
  onOpenLayer: (layer: MemoryLayer) => void;
  onOpenOrganize: () => void;
  onOpenPreferences: () => void;
  onOpenRelations: () => void;
  onOpenTimeline: () => void;
  summary: Record<string, unknown>;
}

/**
 * Pipeline-first Memory composition: the Evidence -> Atom -> Book flow is the
 * catalog's primary navigation, not an illustration hidden behind a summary.
 * The stages switch the visible layer, the governance ledger hangs off the
 * rail it describes, and the provenance promise closes the frame.
 */
export function MemoryPipeline({
  activeLayer,
  onOpenLayer,
  onOpenOrganize,
  onOpenPreferences,
  onOpenRelations,
  onOpenTimeline,
  summary,
}: MemoryPipelineProps) {
  const identity = useProductIdentity();
  const projection = asRecord(summary.projection);
  const timelineCounts = asRecord(summary.activityTimelineCounts);
  const governanceCounts = asRecord(summary.governanceProposalCounts);
  const latestTimeline = asRecord(summary.latestActivityTimeline);
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
  const pendingGovernance = numberValue(summary.needsReviewSourceCount)
    + numberValue(governanceCounts.preview)
    + numberValue(timelineCounts.draft);
  const projectionSignal = describeProjection(projection);

  return (
    <section className="memory-pipeline" aria-labelledby="memory-pipeline-title">
      <header className="memory-pipeline__masthead">
        <div className="memory-pipeline__voice">
          <span>可追溯记忆</span>
          <h2 id="memory-pipeline-title">把重要的事整理好，需要时随时找回</h2>
          <p>
            原始记录先成为可核对的来源，再整理成记忆，最后按主题组织；每一步都能回到上一步核对。
          </p>
        </div>
        <div className="memory-pipeline__actions" aria-label="记忆辅助视图">
          <Button leadingIcon={<Network size={15} />} onClick={onOpenRelations} size="small" variant="quiet">
            关系图
          </Button>
          <Button leadingIcon={<Sparkles size={15} />} onClick={onOpenOrganize} size="small">
            让{identity.assistantName}整理
          </Button>
        </div>
      </header>

      <ol className="memory-pipeline__flow" aria-label="记忆内容分类">
        <PipelineStage
          active={activeLayer === 'evidence'}
          code="来源"
          count={evidenceCount}
          description="查看哪些输入、语音和主动记录可用于整理记忆。"
          detail={`输入法 ${numberValue(summary.inputMethodEvidenceCount)} · 语音 ${numberValue(summary.voiceEvidenceCount)} · 伙伴主动记录 ${agentCapturedEvidenceCount}`}
          icon={Archive}
          index="01"
          label="来源记录"
          onClick={() => onOpenLayer('evidence')}
          stage="evidence"
        />
        <PipelineLink label="整理后可查看" />
        <PipelineStage
          active={activeLayer === 'atoms'}
          code="记忆"
          count={currentAtomCount}
          description="查看已经整理好的长期记忆、当前状态和来源。"
          detail={`全部 ${atomTotalCount} · 历史 ${historicalAtomCount}`}
          icon={Tags}
          index="02"
          label="记忆"
          onClick={() => onOpenLayer('atoms')}
          stage="atoms"
        />
        <PipelineLink label="按主题归类" />
        <PipelineStage
          active={activeLayer === 'books'}
          code="主题"
          count={numberValue(summary.memoryBookCount)}
          description="按主题浏览相关记忆，不会丢失每条记忆的来源。"
          detail={`${numberValue(summary.memoryTagCount)} 个关系标签`}
          icon={BookOpen}
          index="03"
          label="长期主题"
          onClick={() => onOpenLayer('books')}
          stage="books"
        />
      </ol>

      <footer className="memory-pipeline__ledger">
        <div className="memory-pipeline__meters" aria-label="记忆整理状态">
          <PipelineMeter
            detail={projectionSignal.detail}
            label="检索索引"
            tone={projectionSignal.tone}
          />
          <PipelineMeter
            detail={pendingGovernance ? `${pendingGovernance} 项等待处理` : '没有待处理草案'}
            label="待确认"
            tone={pendingGovernance ? 'warning' : 'success'}
          />
          <PipelineMeter
            detail={latestTimelineStatus(latestTimeline)}
            label="最近整理"
            tone={stringValue(latestTimeline.status) === 'draft' ? 'warning' : 'info'}
          />
        </div>
        <div className="memory-pipeline__trust">
          <ShieldCheck aria-hidden="true" size={16} />
          <div>
            <strong>主题不会替代原始记录</strong>
            <span>从任一主题都能继续查看整理过的记忆和来源；历史状态也会保留。</span>
          </div>
        </div>
        <div className="memory-pipeline__trust-actions">
          <Button leadingIcon={<CalendarClock size={14} />} onClick={onOpenTimeline} size="small" variant="quiet">
            查看时间线
          </Button>
          <Button leadingIcon={<SlidersHorizontal size={14} />} onClick={onOpenPreferences} size="small" variant="quiet">
            记忆偏好
          </Button>
        </div>
      </footer>
    </section>
  );
}

function PipelineStage({
  active,
  code,
  count,
  description,
  detail,
  icon: Icon,
  index,
  label,
  onClick,
  stage,
}: {
  active: boolean;
  code: '来源' | '记忆' | '主题';
  count: number;
  description: string;
  detail: string;
  icon: typeof Archive;
  index: string;
  label: string;
  onClick: () => void;
  stage: MemoryLayer;
}) {
  return (
    <li className="memory-pipeline__stage" data-active={active || undefined} data-stage={stage}>
      <button aria-label={`${code} · ${label} · ${count} 项`} aria-pressed={active} onClick={onClick} type="button">
        <span className="memory-pipeline__stage-head">
          <span className="memory-pipeline__stage-index">{index}</span>
          <span className="memory-pipeline__stage-icon"><Icon aria-hidden="true" size={16} /></span>
          <span className="memory-pipeline__stage-count">{count}<small>项</small></span>
        </span>
        <span className="memory-pipeline__stage-title">
          <small>{label}</small>
          <strong>{code}</strong>
        </span>
        <span className="memory-pipeline__stage-copy">
          <p>{description}</p>
          <em title={detail}>{detail}</em>
        </span>
      </button>
    </li>
  );
}

function PipelineLink({ label }: { label: string }) {
  return (
    <li className="memory-pipeline__link" aria-hidden="true">
      <i />
      <span>{label}<ArrowRight size={14} /></span>
    </li>
  );
}

function PipelineMeter({
  detail,
  label,
  tone,
}: {
  detail: string;
  label: string;
  tone: 'success' | 'warning' | 'info';
}) {
  return (
    <div className="memory-pipeline__meter" data-tone={tone}>
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
