import {
  Archive,
  ArrowRight,
  BookOpen,
  CalendarClock,
  GitBranch,
  Network,
  ShieldCheck,
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
  onOpenRelations: () => void;
  onOpenTimeline: () => void;
  summary: Record<string, unknown>;
}

export function MemorySystemOverview({
  activeLayer,
  onOpenLayer,
  onOpenOrganize,
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
          <span>Governed memory · 可追溯记忆</span>
          <h2 id="memory-system-overview-title">每条长期记忆，都能回到它的依据</h2>
          <p>
            <strong>Evidence</strong> 只接收输入法、语音和 Agent 主动记录，
            <strong>Atom</strong> 承载可审阅的记忆单元，<strong>Book</strong> 只组织 Atom。
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

      <div className="memory-system-overview__signals" aria-label="记忆治理状态">
        <StatusSignal
          detail={projectionSignal.detail}
          label="检索投影"
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

      <ol className="memory-architecture" aria-label="Evidence → Atom → Book">
        <MemoryLayerStage
          active={activeLayer === 'evidence'}
          code="Evidence"
          count={evidenceCount}
          description="只保留进入长期记忆链的用户来源；命令、工具过程和非持久审计不会计入。"
          detail={`输入法 ${numberValue(summary.inputMethodEvidenceCount)} · 语音 ${numberValue(summary.voiceEvidenceCount)} · Agent 主动记录 ${agentCapturedEvidenceCount}`}
          icon={Archive}
          index="01"
          label="证据"
          onClick={() => onOpenLayer('evidence')}
        />
        <MemoryLayerConnector label="派生并审核" />
        <MemoryLayerStage
          active={activeLayer === 'atoms'}
          code="Atom"
          count={currentAtomCount}
          description="从 Evidence 派生的最小可审阅记忆单元；保留类型、状态与来源引用。"
          detail={`全部 ${atomTotalCount} · 历史 ${historicalAtomCount}`}
          icon={Tags}
          index="02"
          label="记忆单元"
          onClick={() => onOpenLayer('atoms')}
        />
        <MemoryLayerConnector label="按主题聚合" />
        <MemoryLayerStage
          active={activeLayer === 'books'}
          code="Book"
          count={numberValue(summary.memoryBookCount)}
          description="面向检索的主题聚合，只引用 Atom，不复制一份新的事实。"
          detail={`${numberValue(summary.memoryTagCount)} 个关系标签`}
          icon={BookOpen}
          index="03"
          label="主题书"
          onClick={() => onOpenLayer('books')}
        />
      </ol>

      <div className="memory-system-overview__trust-note">
        <ShieldCheck aria-hidden="true" size={17} />
        <div>
          <strong>Book 不是第二真相源</strong>
          <span>从任一 Book 打开引用，可沿 Atom 继续回到 Evidence；历史状态也保留稳定引用。</span>
        </div>
        <Button leadingIcon={<CalendarClock size={14} />} onClick={onOpenTimeline} size="small" variant="quiet">
          查看时间线
        </Button>
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
  code: 'Evidence' | 'Atom' | 'Book';
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
