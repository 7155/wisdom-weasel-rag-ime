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

interface MemorySystemOverviewProps {
  activeLayer: MemoryLayer;
  onOpenLayer: (layer: MemoryLayer) => void;
  onOpenOrganize: () => void;
  onOpenPreferences: () => void;
  onOpenRelations: () => void;
  onOpenTimeline: () => void;
  summary: Record<string, unknown>;
}

export function MemorySystemOverview({
  activeLayer,
  onOpenLayer,
  onOpenOrganize,
  onOpenPreferences,
  onOpenRelations,
  onOpenTimeline,
  summary,
}: MemorySystemOverviewProps) {
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
    <section className="memory-system-overview" aria-labelledby="memory-system-overview-title">
      <div className="memory-system-overview__headline">
        <div>
          <span>可追溯记忆</span>
          <h2 id="memory-system-overview-title">把重要的事整理好，需要时随时找回</h2>
          <p>
            这里汇总记录来源、已整理记忆和主题；需要核对时，每条结论都能回到它的来源。
          </p>
        </div>
        <div className="memory-system-overview__primary-actions" aria-label="记忆辅助视图">
          <Button leadingIcon={<Network size={15} />} onClick={onOpenRelations} size="small" variant="quiet">
            关系图
          </Button>
          <Button leadingIcon={<Sparkles size={15} />} onClick={onOpenOrganize} size="small">
            让{identity.assistantName}整理
          </Button>
        </div>
      </div>

      <div className="memory-system-overview__signals" aria-label="记忆整理状态">
        <StatusSignal
          detail={projectionSignal.detail}
          label="检索索引"
          tone={projectionSignal.tone}
        />
        <StatusSignal
          detail={pendingGovernance ? `${pendingGovernance} 项等待处理` : '没有待处理草案'}
          label="待确认"
          tone={pendingGovernance ? 'warning' : 'success'}
        />
        <StatusSignal
          detail={latestTimelineStatus(latestTimeline)}
          label="最近整理"
          tone={stringValue(latestTimeline.status) === 'draft' ? 'warning' : 'info'}
        />
      </div>

      <ol className="memory-architecture" aria-label="记忆内容分类">
        <MemoryLayerStage
          active={activeLayer === 'evidence'}
          code="来源"
          count={evidenceCount}
          description="查看哪些输入、语音和主动记录可用于整理记忆。"
          detail={`输入法 ${numberValue(summary.inputMethodEvidenceCount)} · 语音 ${numberValue(summary.voiceEvidenceCount)} · 伙伴主动记录 ${agentCapturedEvidenceCount}`}
          icon={Archive}
          index="01"
          label="来源记录"
          onClick={() => onOpenLayer('evidence')}
        />
        <MemoryLayerConnector label="整理后可查看" />
        <MemoryLayerStage
          active={activeLayer === 'atoms'}
          code="记忆"
          count={currentAtomCount}
          description="查看已经整理好的长期记忆、当前状态和来源。"
          detail={`全部 ${atomTotalCount} · 历史 ${historicalAtomCount}`}
          icon={Tags}
          index="02"
          label="记忆"
          onClick={() => onOpenLayer('atoms')}
        />
        <MemoryLayerConnector label="按主题归类" />
        <MemoryLayerStage
          active={activeLayer === 'books'}
          code="主题"
          count={numberValue(summary.memoryBookCount)}
          description="按主题浏览相关记忆，不会丢失每条记忆的来源。"
          detail={`${numberValue(summary.memoryTagCount)} 个关系标签`}
          icon={BookOpen}
          index="03"
          label="长期主题"
          onClick={() => onOpenLayer('books')}
        />
      </ol>

      <div className="memory-system-overview__trust-note">
        <ShieldCheck aria-hidden="true" size={17} />
        <div>
          <strong>主题不会替代原始记录</strong>
          <span>从任一主题都能继续查看整理过的记忆和来源；历史状态也会保留。</span>
        </div>
        <div className="memory-system-overview__trust-actions">
          <Button leadingIcon={<CalendarClock size={14} />} onClick={onOpenTimeline} size="small" variant="quiet">
            查看时间线
          </Button>
          <Button leadingIcon={<SlidersHorizontal size={14} />} onClick={onOpenPreferences} size="small" variant="quiet">
            记忆偏好
          </Button>
        </div>
      </div>
    </section>
  );
}

function StatusSignal({
  detail,
  label,
  tone,
}: {
  detail: string;
  label: string;
  tone: 'success' | 'warning' | 'info';
}) {
  return (
    <div className="memory-system-overview__signal" data-tone={tone}>
      <i aria-hidden="true" />
      <span><strong>{label}</strong><small>{detail}</small></span>
    </div>
  );
}

function MemoryLayerStage({
  active,
  code,
  count,
  description,
  detail,
  icon: Icon,
  index,
  label,
  onClick,
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
}) {
  return (
    <li className="memory-architecture__stage" data-active={active || undefined}>
      <button aria-label={`${code} · ${label} · ${count} 项`} aria-pressed={active} onClick={onClick} type="button">
        <span className="memory-architecture__index">{index}</span>
        <span className="memory-architecture__icon"><Icon aria-hidden="true" size={17} /></span>
        <span className="memory-architecture__copy">
          <small>{label}</small>
          <strong>{code}</strong>
          <p>{description}</p>
          <em>{detail}</em>
        </span>
        <span className="memory-architecture__count">{count}<small>项</small></span>
      </button>
    </li>
  );
}

function MemoryLayerConnector({ label }: { label: string }) {
  return (
    <li className="memory-architecture__connector" aria-hidden="true">
      <span>{label}</span>
      <ArrowRight size={16} />
    </li>
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
