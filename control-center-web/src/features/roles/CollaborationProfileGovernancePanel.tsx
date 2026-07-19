import { Check, FileDiff, Fingerprint, LockKeyhole, ReceiptText, ShieldCheck } from 'lucide-react';
import type { CollaborationProfileGovernanceProjection } from './agent-definition-fixtures';
import './collaboration-profile-governance.css';

export function CollaborationProfileGovernancePanel({
  projection,
}: {
  projection: CollaborationProfileGovernanceProjection;
}) {
  return <section className="profile-governance" aria-label="角色书持久化检查">
    <header><span><LockKeyhole size={14} /><strong>持久化检查</strong></span><small>只读 · pointer r{projection.pointerRevision}</small></header>
    <dl>
      <div><dt><Fingerprint size={14} />内容地址</dt><dd title={projection.activeContentHash}>{shortHash(projection.activeContentHash)}</dd></div>
      <div><dt><ShieldCheck size={14} />签名来源</dt><dd>{projection.signerId}</dd></div>
      <div><dt><ReceiptText size={14} />编译回执</dt><dd>{projection.compileReceipt.receiptId}</dd></div>
      <div><dt>Binding 版本</dt><dd>{projection.compileReceipt.bindingRevision}</dd></div>
    </dl>
    <ol aria-label="角色书安全流水线">{projection.pipelineChecks.map((step) => <li key={step}><Check size={12} />{pipelineLabel(step)}</li>)}</ol>
    <section className="profile-governance__diff" aria-label="角色书能力差异">
      <header><span><FileDiff size={14} /><strong>能力差异</strong></span><small>{projection.diff.previousVersion ? `v${projection.diff.previousVersion} → ` : ''}v{projection.diff.currentVersion}</small></header>
      <p><b>有效</b><span>{projection.compileReceipt.effectiveCapabilities.join(' · ') || '无'}</span></p>
      <p data-change="removed"><b>收窄</b><span>{projection.diff.removedCapabilities.join(' · ') || '无变化'}</span></p>
      {projection.diff.addedCapabilities.length ? <p data-change="blocked"><b>阻止</b><span>{projection.diff.addedCapabilities.join(' · ')}</span></p> : null}
    </section>
  </section>;
}

function shortHash(value: string): string {
  return value.length > 24 ? `${value.slice(0, 15)}…${value.slice(-8)}` : value;
}

function pipelineLabel(value: CollaborationProfileGovernanceProjection['pipelineChecks'][number]): string {
  return ({
    inspect: '检查', validate: '校验', compile: '编译', 'dry-run': '试运行', stage: '暂存', activate: '原子启用',
  } as const)[value];
}
