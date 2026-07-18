import {
  Archive,
  ArrowRight,
  BookOpen,
  CalendarClock,
  DatabaseZap,
  Network,
  ShieldCheck,
  Tags,
  UserRoundCog,
} from 'lucide-react';
import { Button } from '@/components/primitives';
import { asRecord, numberValue, stringValue } from '@/features/overview/management-ui';

interface MemorySystemOverviewProps {
  onOpenLayer: (layer: 'evidence' | 'atoms' | 'books' | 'roleBooks') => void;
  onOpenOrganize: () => void;
  onOpenTimeline: () => void;
  summary: Record<string, unknown>;
}

export function MemorySystemOverview({
  onOpenLayer,
  onOpenOrganize,
  onOpenTimeline,
  summary,
}: MemorySystemOverviewProps) {
  const projection = asRecord(summary.projection);
  const timelineCounts = asRecord(summary.activityTimelineCounts);
  const roleBookCounts = asRecord(summary.roleBookRevisionCounts);
  const governanceCounts = asRecord(summary.governanceProposalCounts);
  const latestTimeline = asRecord(summary.latestActivityTimeline);
  const pendingGovernance = numberValue(summary.needsReviewSourceCount)
    + numberValue(governanceCounts.preview)
    + numberValue(timelineCounts.draft)
    + numberValue(roleBookCounts.draft);
  const projectionSignal = describeProjection(projection);
  const inputEvidenceCount = numberValue(summary.evidenceSourceCount);
  const agentEvidenceCount = numberValue(summary.agentEvidenceCount);

  return (
    <section className="memory-system-overview" aria-labelledby="memory-system-overview-title">
      <div className="memory-system-overview__headline">
        <div>
          <span>Personal Context Core</span>
          <h2 id="memory-system-overview-title">个人上下文</h2>
          <p>证据、当前事实、主题关系和会话角色保持独立生命周期。</p>
        </div>
        <div className="memory-system-overview__signals" aria-label="记忆系统状态">
          <StatusSignal
            detail={projectionSignal.detail}
            label="召回投影"
            tone={projectionSignal.tone}
          />
          <StatusSignal
            detail={pendingGovernance ? `${pendingGovernance} 项等待处理` : '没有待处理草案'}
            label="治理队列"
            tone={pendingGovernance ? 'warning' : 'success'}
          />
          <StatusSignal
            detail={latestTimelineStatus(latestTimeline)}
            label="最近时间线"
            tone={stringValue(latestTimeline.status) === 'draft' ? 'warning' : 'info'}
          />
        </div>
      </div>

      <div className="memory-system-overview__pipeline" aria-label="个人上下文数据层">
        <PipelineStage
          detail={`输入 ${inputEvidenceCount} · Agent ${agentEvidenceCount}`}
          icon={Archive}
          label="可追溯证据"
          onClick={() => onOpenLayer('evidence')}
          value={inputEvidenceCount + agentEvidenceCount}
        />
        <ArrowRight aria-hidden="true" className="memory-system-overview__arrow" size={16} />
        <PipelineStage
          detail={`共 ${numberValue(summary.memoryAtomTotalCount, numberValue(summary.currentAtomCount, numberValue(summary.memoryAtomCount)) + numberValue(summary.historicalAtomCount, numberValue(summary.memoryAtomArchivedCount)) + numberValue(summary.memoryAtomSourceArchiveCount))} 条 · 历史 ${numberValue(summary.historicalAtomCount, numberValue(summary.memoryAtomArchivedCount))} · 碎片证据 ${numberValue(summary.memoryAtomSourceArchiveCount)}`}
          icon={Tags}
          label="当前事实"
          onClick={() => onOpenLayer('atoms')}
          value={numberValue(summary.currentAtomCount, numberValue(summary.memoryAtomCount))}
        />
        <ArrowRight aria-hidden="true" className="memory-system-overview__arrow" size={16} />
        <PipelineStage
          detail="主题与关系"
          icon={BookOpen}
          label="主题书"
          onClick={() => onOpenLayer('books')}
          value={numberValue(summary.memoryBookCount)}
        />
        <ArrowRight aria-hidden="true" className="memory-system-overview__arrow" size={16} />
        <PipelineStage
          detail="会话身份"
          icon={UserRoundCog}
          label="角色书"
          onClick={() => onOpenLayer('roleBooks')}
          value={numberValue(roleBookCounts.active)}
        />
      </div>

      <div className="memory-system-overview__footer">
        <div className="memory-system-overview__quick-stats">
          <span><DatabaseZap size={15} />{numberValue(summary.completeInputCount, numberValue(summary.eventCount))} 条完整输入</span>
          <span><Network size={15} />{numberValue(summary.memoryTagCount)} 个关系标签</span>
          <span><CalendarClock size={15} />{numberValue(timelineCounts.approved)} 天已批准</span>
          <span><ShieldCheck size={15} />{numberValue(summary.forgottenSourceCount)} 条已隔离</span>
        </div>
        <div className="memory-system-overview__actions">
          <Button onClick={() => onOpenLayer('atoms')} size="small" variant="quiet">查看事实</Button>
          <Button onClick={onOpenOrganize} size="small" variant="quiet">处理草案</Button>
          <Button leadingIcon={<CalendarClock size={15} />} onClick={onOpenTimeline} size="small">
            打开时间线
          </Button>
        </div>
      </div>
    </section>
  );
}

function StatusSignal({ detail, label, tone }: { detail: string; label: string; tone: 'success' | 'warning' | 'info' }) {
  return (
    <div className="memory-system-overview__signal" data-tone={tone}>
      <i aria-hidden="true" />
      <span><strong>{label}</strong><small>{detail}</small></span>
    </div>
  );
}

function PipelineStage({
  detail,
  icon: Icon,
  label,
  onClick,
  value,
}: {
  detail: string;
  icon: typeof Archive;
  label: string;
  onClick: () => void;
  value: number;
}) {
  return (
    <button className="memory-system-overview__stage" onClick={onClick} type="button">
      <span><Icon aria-hidden="true" size={16} /></span>
      <div><small>{label}</small><strong>{value}</strong><em>{detail}</em></div>
      <ArrowRight aria-hidden="true" className="memory-system-overview__stage-open" size={15} />
    </button>
  );
}

function latestTimelineStatus(value: Record<string, unknown>): string {
  const date = stringValue(value.date);
  if (!date) return '尚未生成';
  const status = ({ draft: '待审核', approved: '已批准', rejected: '已驳回', superseded: '已更新' } as Record<string, string>)[stringValue(value.status)] ?? '已整理';
  return `${date.slice(5)} ${status}`;
}

function describeProjection(value: Record<string, unknown>): { detail: string; tone: 'success' | 'warning' | 'info' } {
  if (!Object.keys(value).length) return { detail: '状态未知', tone: 'info' };
  if (value.fresh === true) {
    return { detail: `${numberValue(value.retrievalDocuments)} 份检索文档`, tone: 'success' };
  }
  if (value.projectionInitialized === false) return { detail: '尚未初始化', tone: 'warning' };
  const dead = numberValue(value.dead);
  if (dead) return { detail: `${dead} 项需要人工处理`, tone: 'warning' };
  const backlog = numberValue(value.backlog);
  if (backlog) return { detail: `${backlog} 项正在追赶`, tone: 'warning' };
  return { detail: '等待重新校验', tone: 'warning' };
}
