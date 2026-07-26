import { CircleCheck, FileCheck2, GitCommitHorizontal, LockKeyhole, ShieldAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import type { RequirementAnchorReadProjection, RoomRequirementsReadProjection } from './room-requirements-read-model';
import './room-requirements-control-plane.css';

export function RoomRequirementsControlPlane({ projection }: { projection: RoomRequirementsReadProjection }) {
  const catalog = projection.catalog;
  const receiptAssessments = projection.receiptAssessments;
  const catalogIsCurrent = !projection.deliveryGate
    || projection.deliveryGate.catalogRevisionId === catalog?.catalogRevisionId;
  return <section className="room-requirements" aria-label={`${projection.rootId} 需求、证明与审查`}>
    <header className="room-requirements__header">
      <span><strong>需求、验证与复核</strong><small>只读 · {sourceLabel(projection.projectionSource)}</small></span>
      <b data-status={catalogIsCurrent ? 'neutral' : 'warning'}>{catalogIsCurrent ? '当前目录' : '旧目录警告'}</b>
    </header>

    <section className="room-requirements__originals" aria-label="原始需求">
      <SectionTitle title="原始需求" detail="永久保留，不可修改" icon={<LockKeyhole size={14} />} />
      {projection.anchors.length
        ? projection.anchors.map((anchor) => <OriginalRequirement key={anchor.anchor.anchorId} value={anchor} />)
        : <Empty>未读取到原始需求锚点。</Empty>}
    </section>

    <section aria-label="可修订需求目录">
      <SectionTitle title="可修订需求目录" detail="拆分结果可换版，原文不随之改写" icon={<GitCommitHorizontal size={14} />} />
      {catalog ? <>
        <dl className="room-requirements__metadata">
          <div><dt>目录版本</dt><dd>第 {catalog.revision} 版 · {catalog.catalogRevisionId}</dd></div>
          <div><dt>取代版本</dt><dd>{catalog.supersedesRevisionId || '初始版本'}</dd></div>
          <div><dt>变更原因</dt><dd>{catalog.changeReason}</dd></div>
          <div><dt>来源记录</dt><dd>{formatRecord(catalog.provenance)}</dd></div>
          <div><dt>载荷哈希</dt><dd className="room-requirements__hash">{catalog.payloadHash}</dd></div>
        </dl>
        <div className="room-requirements__catalog-grid">
          <CatalogList title="需求目录项" items={catalog.items} kind="item" />
          <CatalogList title="验收标准" items={catalog.acceptanceCriteria} kind="criterion" />
        </div>
      </> : <Empty>当前任务还没有需求目录版本。</Empty>}
    </section>

    <section aria-label="验证记录">
      <SectionTitle title="验证记录" detail="只认系统实际执行结果，伙伴的文字说明不能代替验证" icon={<FileCheck2 size={14} />} />
      {receiptAssessments.length ? <div className="room-requirements__table-wrap"><table>
        <thead><tr><th>类型 / 回执</th><th>签发者</th><th>提交</th><th>输出 / 产物哈希</th><th>状态</th></tr></thead>
        <tbody>{receiptAssessments.map(({ receipt, reasons, status }) => <tr key={receipt.receiptId} data-proof-status={status}>
          <td data-label="类型 / 回执"><strong>{receiptTypeLabel(receipt.receiptType)}</strong><small>{receipt.receiptId}</small></td>
          <td data-label="签发者"><span>{receipt.verifier}</span><small>{receipt.environment}</small></td>
          <td data-label="提交"><span>{receipt.sourceCommit}</span><small>{receipt.commandOrAction}</small></td>
          <td data-label="输出 / 产物哈希"><code>{shortHash(receipt.outputHash)}</code><code>{shortHash(receipt.artifactHash)}</code></td>
          <td data-label="状态"><b data-status={status}>{proofStatusLabel(status)}</b>{reasons.length ? <small>{reasons.map(reasonLabel).join(' · ')}</small> : null}</td>
        </tr>)}</tbody>
      </table></div> : <Empty>还没有可核验的结果。伙伴的文字说明不会补进这里。</Empty>}
    </section>

    <section aria-label="收工与交付检查">
      <SectionTitle title="收工与交付检查" detail="先过任务收工门，再查看额外的同伴与证据观察" icon={<ShieldAlert size={14} />} />
      <div className="room-requirements__gate-grid">
        <article className="room-requirements__gate" data-gate-status="enforced">
          <header><strong>任务收工检查</strong><b data-status="observed_pass">始终启用</b></header>
          <p>每次交付都要带上原始需求、验收覆盖和真实工具回执。缺少或引用错误时，系统会拒绝收工，并要求继续修正、交接、等待或报告阻塞。</p>
          <dl>
            <div><dt>原始需求</dt><dd>必须保留并确认</dd></div>
            <div><dt>验收覆盖</dt><dd>逐项核对当前任务</dd></div>
            <div><dt>完成证据</dt><dd>只接受系统签发的有效回执</dd></div>
          </dl>
        </article>
        <article className="room-requirements__gate" data-gate-status={projection.deliveryGate?.gateStatus ?? 'unknown'}>
          <header><strong>额外交付观察</strong><b data-status={projection.deliveryGate?.gateStatus ?? 'unknown'}>{gateStatusLabel(projection.deliveryGate?.gateStatus)}</b></header>
          <p>同伴复核、用户旅程和跨证据检查当前用于提示风险，不会在生产环境额外增加一道终态拦截。</p>
          <GateDetails projection={projection} />
        </article>
      </div>
    </section>

    <section aria-label="冲突与同伴审查">
      <SectionTitle title="冲突与同伴审查" detail="只显示系统实际记录，不由界面猜测" icon={<CircleCheck size={14} />} />
      <div className="room-requirements__review-grid">
        <ReadProjectionList title="冲突清单" empty="没有发现冲突。" rows={projection.conflicts.map((conflict) => ({
          id: conflict.conflictId,
          primary: `${conflict.leftItemId} ↔ ${conflict.rightItemId}`,
          secondary: `${conflictKindLabel(conflict.conflictKind)} · ${conflict.status === 'open' ? '未解决' : '已解决'}${conflict.resolution ? ` · ${conflict.resolution}` : ''}`,
        }))} />
        <ReadProjectionList title="同伴复核" empty="还没有同伴复核记录。" rows={projection.peerReviewRounds.map((round) => ({
          id: round.roundId,
          primary: round.reviewerActorRefs.join('、') || '尚无审查者',
          secondary: `${reviewStatusLabel(round.status)} · ${round.verdicts.join(' / ') || '待判断'} · ${round.receiptRef || '无回执'}`,
        }))} />
      </div>
    </section>
  </section>;
}

function OriginalRequirement({ value }: { value: RequirementAnchorReadProjection }) {
  const integrity = value.integrityStatus;
  const legacy = value.anchor.authenticity === 'legacy_quarantined';
  return <article className="room-requirements__original" data-integrity={integrity}>
    <header><span><strong>{value.anchor.anchorId}</strong><small>原始序号 {value.anchor.rootSequence} · {value.anchor.originalByteLength} bytes</small></span><b data-status={integrity === 'verified' && !legacy ? 'neutral' : 'warning'}>{legacy ? '历史文本隔离' : integrityLabel(integrity)}</b></header>
    <pre tabIndex={0} aria-label={`${value.anchor.anchorId} 原始需求只读文本`}>{value.originalText}</pre>
    <dl><div><dt>原文 SHA-256</dt><dd>{value.anchor.originalContentSha256}</dd></div><div><dt>来源</dt><dd>{formatRecord(value.anchor.provenance)}</dd></div></dl>
  </article>;
}

function GateDetails({ projection }: { projection: RoomRequirementsReadProjection }) {
  const gate = projection.deliveryGate;
  if (!gate) return <Empty>交付观察尚未上报，状态未知。</Empty>;
  const journeys = gate.proofMatrix.filter((entry) => recordString(entry.criterionKind) === 'user_journey');
  return <dl>
    <div><dt>盲审</dt><dd>{reviewStatusLabel(gate.blindReviewStatus)}</dd></div>
    <div><dt>用户旅程</dt><dd>{journeys.length ? `${journeys.filter((item) => item.passed === true).length} / ${journeys.length} 通过` : '缺失'}</dd></div>
    <div><dt>阻塞与未知</dt><dd>{gate.reasons.length ? gate.reasons.map(reasonLabel).join(' · ') : '无'}</dd></div>
    <div><dt>目标提交</dt><dd>{gate.targetCommit}</dd></div>
  </dl>;
}

function CatalogList({ items, kind, title }: { items: Record<string, unknown>[]; kind: 'item' | 'criterion'; title: string }) {
  return <div className="room-requirements__catalog-list"><h4>{title}</h4>{items.length ? <ol>{items.map((item, index) => {
    const id = recordString(item[kind === 'item' ? 'itemId' : 'criterionId']) || `${kind}-${index + 1}`;
    const statement = recordString(item.statement) || '未提供描述';
    const detail = kind === 'criterion'
      ? `${recordString(item.acceptanceCriterionFullNameZh) || '验收标准'} · ${stringArray(item.expectedReceiptTypes).map(receiptTypeLabel).join('、') || '尚未说明验证方式'}`
      : `${recordString(item.kind) || 'unknown'} · ${recordString(item.state) || 'unknown'}`;
    return <li key={id}><strong>{statement}</strong><small>{id} · {detail}</small></li>;
  })}</ol> : <Empty>当前版本没有条目。</Empty>}</div>;
}

function ReadProjectionList({ empty, rows, title }: { title: string; empty: string; rows: { id: string; primary: string; secondary: string }[] }) {
  return <div className="room-requirements__read-list"><h4>{title}</h4>{rows.length ? <ul>{rows.map((row) => <li key={row.id}><strong>{row.primary}</strong><small>{row.id} · {row.secondary}</small></li>)}</ul> : <Empty>{empty}</Empty>}</div>;
}

function SectionTitle({ detail, icon, title }: { title: string; detail: string; icon: ReactNode }) {
  return <header className="room-requirements__section-title"><span>{icon}<strong>{title}</strong></span><small>{detail}</small></header>;
}

function Empty({ children }: { children: ReactNode }) { return <p className="room-requirements__empty">{children}</p>; }
function sourceLabel(value: RoomRequirementsReadProjection['projectionSource']) { return value === 'canonical_fixture' ? '固定验收数据' : '系统只读结果'; }
function integrityLabel(value: 'verified' | 'tampered') { return ({ verified: '原文哈希已核验', tampered: '原文校验失败' } as const)[value]; }
function receiptTypeLabel(value: string) { return ({ test: '测试', build: '构建', install: '安装', evidence: '证据' } as Record<string, string>)[value] ?? value; }
function proofStatusLabel(value: string) { return ({ observed_pass: '已观察通过', failed: '执行失败', stale: '旧版或错误提交', tampered: '回执不可信' } as Record<string, string>)[value] ?? value; }
function gateStatusLabel(value?: string) { return value === 'observed_pass' ? '已观察通过' : value === 'warn_blocked' ? '有警告 / 阻塞项' : '未知'; }
function reviewStatusLabel(value: string) { return ({ pending: '待审查', passed: '已通过', failed: '未通过', conflict: '存在冲突', unavailable: '不可用' } as Record<string, string>)[value] ?? value; }
function conflictKindLabel(value: string) { return ({ contradiction: '矛盾', unknown: '未知', ambiguity: '歧义' } as Record<string, string>)[value] ?? value; }
function reasonLabel(value: string) {
  const prefix = value.split(':', 1)[0];
  return ({
    requirements_without_acceptance_criteria: '需求缺少验收标准', requirements_need_confirmation: '需求等待确认',
    criterion_without_valid_proof: '验收标准缺少有效证明', user_journey_missing: '用户旅程缺失', user_journey_failed: '用户旅程未通过',
    unresolved_conflict_or_unknown: '冲突或未知项未解决', unresolved_blocker: '阻塞项未解决', unresolved_unknown: '未知项未解决',
    blind_review_not_passed: '盲审未通过', cross_root: '来自其他任务的回执', old_catalog_revision: '引用旧目录版本',
    untrusted_verifier: '签发者不可信', invalid_hash: '哈希格式无效', wrong_commit: '提交不匹配', non_zero_exit: '命令退出码非零',
  } as Record<string, string>)[prefix] ?? value;
}
function shortHash(value: string) { return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value; }
function formatRecord(value: Record<string, unknown>) {
  const entries = Object.entries(value);
  return entries.length ? entries.map(([key, item]) => `${key}: ${String(item)}`).join(' · ') : '未上报';
}
function recordString(value: unknown) { return typeof value === 'string' ? value : ''; }
function stringArray(value: unknown) { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []; }
