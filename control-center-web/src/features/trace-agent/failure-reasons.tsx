import { AlertTriangle, CheckCircle2, CircleHelp } from 'lucide-react';

/**
 * The public failure taxonomy from PAWOS_REQUIREMENTS_188_188.md.
 * Keep the ids stable: Trace reports and future filters may persist them.
 */
export const FAILURE_REASON_CATEGORIES = [
  { id: 'security_policy', label: '安全/审核策略拒绝' },
  { id: 'approval_permission', label: '权限/审批' },
  { id: 'model_rejection', label: '模型拒绝' },
  { id: 'parameter_schema', label: '参数或 Schema 验证' },
  { id: 'tool_execution', label: 'Tool 执行或非零退出' },
  { id: 'timeout_cancel', label: '超时/取消' },
  { id: 'runtime_network', label: 'Runtime/网络' },
  { id: 'persistence', label: '持久化' },
  { id: 'resource_unavailable', label: '资源不可用' },
] as const;

export type FailureReasonCategoryId = (typeof FAILURE_REASON_CATEGORIES)[number]['id'];

export type FailureReasonEvidence = {
  id: string;
  source: string;
  status: string;
  title: string;
  summary: string;
  createdAtMs: number;
  traceId?: string;
  code?: string;
};

const CODE_SIGNALS: ReadonlyArray<readonly [FailureReasonCategoryId, RegExp]> = [
  ['model_rejection', /(?:model|provider).*(?:refus|reject)|(?:refus|reject).*(?:model|provider)/i],
  ['security_policy', /(?:safety|security|policy|moderation|review_policy).*(?:deny|block|reject|refus)/i],
  ['approval_permission', /approval|permission|forbidden|unauthori[sz]ed|access_denied/i],
  ['parameter_schema', /schema|validation|invalid_argument|resource_revision|revision_conflict/i],
  ['tool_execution', /tool|non_?zero|exit_?code|command_?failed/i],
  ['timeout_cancel', /timeout|timed_?out|cancel|abort|deadline/i],
  ['runtime_network', /runtime|network|gateway|sidecar|connection|socket|active_?turn/i],
  ['persistence', /persist|storage|database|sqlite|jsonl|write|read|save/i],
  ['resource_unavailable', /unavailable|not_?found|missing|resource/i],
];

const CATEGORY_SIGNALS: ReadonlyArray<readonly [FailureReasonCategoryId, RegExp]> = [
  ['model_rejection', /(模型拒绝|模型未能|model rejection|model refused|model refusal|provider refused)/i],
  ['security_policy', /(安全策略|审核策略|策略拒绝|policy denied|safety refused|review policy)/i],
  ['approval_permission', /(权限|审批|授权|approval|permission|forbidden|not authorized|access denied)/i],
  ['parameter_schema', /(参数|schema|validation|验证失败|版本冲突|resource.?revision|invalid argument|invalid .*schema)/i],
  ['tool_execution', /(tool .*?(执行|execution)|执行失败|非零退出|non.?zero|exit code|command failed|tool failed)/i],
  ['timeout_cancel', /(超时|timeout|timed out|取消|cancel(?:led|ed)?|aborted)/i],
  ['runtime_network', /(runtime|网络|network|连接|connection|socket|gateway|sidecar|host unavailable|active turn|仍有 active turn)/i],
  ['persistence', /(持久化|保存|写入|读取|数据库|database|jsonl|sqlite|persist|storage)/i],
  ['resource_unavailable', /(资源不可用|不可用|unavailable|not found|missing|不存在|找不到)/i],
];

/**
 * Classify only when public evidence contains an authoritative signal.
 * Returning null is intentional: an unknown reason must not be disguised as
 * a persistence, Tool, or generic runtime failure.
 */
export function classifyFailureReason(item: FailureReasonEvidence): FailureReasonCategoryId | null {
  const code = item.code?.trim() ?? '';
  if (code) {
    const authoritative = CODE_SIGNALS.find(([, signal]) => signal.test(code))?.[0];
    if (authoritative) return authoritative;
  }
  const text = `${item.title} ${item.summary} ${item.source}`.trim();
  return CATEGORY_SIGNALS.find(([, signal]) => signal.test(text))?.[0] ?? null;
}

function categoryLabel(categoryId: FailureReasonCategoryId): string {
  return FAILURE_REASON_CATEGORIES.find((category) => category.id === categoryId)?.label ?? categoryId;
}

export function TraceFailureReasonPanel({
  evidence,
  loading,
}: {
  evidence: FailureReasonEvidence[];
  loading: boolean;
}) {
  const classified = new Map<FailureReasonCategoryId, FailureReasonEvidence[]>();
  const unclassified: FailureReasonEvidence[] = [];
  for (const item of evidence) {
    const category = classifyFailureReason(item);
    if (!category) {
      unclassified.push(item);
      continue;
    }
    const group = classified.get(category) ?? [];
    group.push(item);
    classified.set(category, group);
  }

  return (
    <section aria-label="失败原因分类" className="trace-agent-failure-reasons">
      <div className="trace-agent-failure-reasons__heading">
        <div>
          <span className="trace-agent-kicker">权威分类</span>
          <h3>失败原因分类</h3>
        </div>
        <span className="trace-agent-failure-reasons__scope">
          {loading ? '读取中' : `${evidence.length} 条原始证据`}
        </span>
      </div>
      <p className="trace-agent-failure-reasons__description">
        只按 Trace、Runtime 和原始对话公开的证据归类；没有公开细节时明确显示 unavailable，不做猜测。
      </p>
      <div className="trace-agent-failure-reasons__list" role="list">
        {FAILURE_REASON_CATEGORIES.map((category) => {
          const items = classified.get(category.id) ?? [];
          return (
            <article
              className={`trace-agent-failure-reasons__item${items.length ? ' trace-agent-failure-reasons__item--found' : ''}`}
              data-category={category.id}
              data-testid={`trace-failure-category-${category.id}`}
              key={category.id}
              role="listitem"
            >
              <div className="trace-agent-failure-reasons__item-heading">
                {items.length ? <CheckCircle2 aria-hidden="true" size={14} /> : <CircleHelp aria-hidden="true" size={14} />}
                <strong>{category.label}</strong>
                <span>{items.length ? `已发现 · ${items.length} 条证据` : 'unavailable'}</span>
              </div>
              {items.length ? (
                <ul>
                  {items.slice(0, 3).map((item) => (
                    <li key={item.id}>
                      <strong>{item.title}</strong>
                      <span>{item.summary}</span>
                    </li>
                  ))}
                  {items.length > 3 ? <li className="trace-agent-failure-reasons__more">另有 {items.length - 3} 条证据，见上方原始证据。</li> : null}
                </ul>
              ) : (
                <p>unavailable：当前 Trace 没有该类别的公开证据。</p>
              )}
            </article>
          );
        })}
      </div>
      {unclassified.length ? (
        <div className="trace-agent-failure-reasons__unknown" role="note">
          <AlertTriangle aria-hidden="true" size={14} />
          <span>
            {unclassified.length} 条证据未能可靠归类；来源细节 unavailable，未强行归因。请查看原始证据。
          </span>
        </div>
      ) : null}
      <p className="trace-agent-failure-reasons__legend">当前已归类：{[...classified.keys()].map(categoryLabel).join('、') || '无'}。</p>
    </section>
  );
}
