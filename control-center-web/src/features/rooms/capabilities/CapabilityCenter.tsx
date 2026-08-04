import { Ban, Check, ChevronDown, Circle, Fingerprint, ReceiptText, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import type { CapabilityCenterProjection, CapabilityProjection, CapabilityStateName, RuntimeRevisionReferenceProjection } from '@/contracts/capability-center-reducer';
import './capability-center.css';

const STATE_ORDER: CapabilityStateName[] = ['available', 'authorized', 'disclosed', 'loaded', 'invoked', 'revoked'];

export function CapabilityCenter({ projection, sessionId }: { projection: CapabilityCenterProjection; sessionId: string }) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const capabilities = Object.values(projection.capabilitiesBySessionId[sessionId] ?? {}).sort((left, right) => left.capabilityId.localeCompare(right.capabilityId));
  return <section className="capability-center" aria-label="能力中心">
    <header><span><ShieldCheck size={16} /><strong>Capability Center</strong></span><small>{sessionId} · cursor {projection.lastSequence}</small></header>
    {projection.needsSnapshot ? <p className="capability-center__warning">事件存在缺口，等待 canonical snapshot；当前投影不继续推进。</p> : null}
    <div className="capability-center__state-header" aria-hidden="true"><i>能力</i>{STATE_ORDER.map((state) => <span key={state}><b>{stateLabel(state)}</b><small>{state}</small></span>)}</div>
    <div className="capability-center__list">
      {capabilities.map((capability) => {
        const open = expanded.has(capability.capabilityId);
        return <article key={capability.capabilityId} data-revoked={capability.states.revoked || undefined}>
          <button type="button" aria-expanded={open} aria-controls={`capability-${safeId(capability.capabilityId)}`} aria-label={`${capability.displayName} ${capability.capabilityId}`} onClick={() => setExpanded(toggle(expanded, capability.capabilityId))}>
            <span><strong>{capability.displayName}</strong><small>{capability.capabilityId}</small></span>
            {STATE_ORDER.map((state) => <StateMark key={state} state={state} active={capability.states[state]} />)}
            <ChevronDown size={14} aria-hidden="true" />
          </button>
          {open ? <CapabilityDetails capability={capability} id={`capability-${safeId(capability.capabilityId)}`} /> : null}
        </article>;
      })}
      {!capabilities.length ? <p className="capability-center__empty">该 Session 没有能力投影。</p> : null}
    </div>
  </section>;
}

function CapabilityDetails({ capability, id }: { capability: CapabilityProjection; id: string }) {
  return <section id={id} className="capability-center__details" aria-label={`${capability.displayName} 检查详情`}>
    <p>{capability.summary}</p>
    <div className="capability-center__references">
      <Reference label="Manifest" reference={capability.manifestRef} />
      <Reference label="Profile" reference={capability.profileRef} />
      {capability.skillRefs.map((reference) => <Reference key={`${reference.id}:${reference.revision}`} label="Skill" reference={reference} />)}
      {capability.toolRefs.map((reference) => <Reference key={`${reference.id}:${reference.revision}`} label="Tool" reference={reference} />)}
      <Reference label="Context" reference={capability.contextRef} />
    </div>
    <section className="capability-center__narrowing" aria-label={`${capability.displayName} 收窄记录`}><header><strong>逐层收窄</strong><small>来自编译/授权回执，不由界面计算</small></header>{capability.narrowedBy.map((item) => <div key={`${item.layer}:${item.receiptId}`} data-decision={item.decision}><span><b>{layerLabel(item.layer)}</b><i>{item.decision === 'removed' ? '移除' : '保留'}</i></span><p>{item.reason}</p><small><ReceiptText size={12} />{item.receiptId}</small></div>)}</section>
    <section className="capability-center__receipts" aria-label={`${capability.displayName} 状态回执`}><header><strong>状态回执</strong><small>{capability.receipts.length} 条</small></header>{capability.receipts.map((receipt) => <span key={receipt.receiptId}><b>{stateLabel(receipt.kind)}</b><i>{receipt.revision}</i><small title={receipt.contentHash}><Fingerprint size={12} />{shortHash(receipt.contentHash)}</small></span>)}</section>
  </section>;
}

function Reference({ label, reference }: { label: string; reference: RuntimeRevisionReferenceProjection }) {
  return <span><small>{label}</small><strong>{reference.id}</strong><i>r{reference.revision} · {reference.receiptId}</i><b title={reference.contentHash}>{shortHash(reference.contentHash)}</b></span>;
}

function StateMark({ active, state }: { active: boolean; state: CapabilityStateName }) {
  const revoked = state === 'revoked';
  return <span className="capability-center__state" data-active={active || undefined} data-state={state} aria-label={`${stateLabel(state)}：${active ? '是' : '否'}`} title={`${stateLabel(state)}：${active ? '是' : '否'}`}>{active ? revoked ? <Ban size={14} /> : <Check size={14} /> : <Circle size={11} />}</span>;
}

function toggle(current: ReadonlySet<string>, value: string): ReadonlySet<string> {
  const next = new Set(current);
  if (next.has(value)) next.delete(value); else next.add(value);
  return next;
}

function stateLabel(value: CapabilityStateName): string {
  return ({ available: '可用', authorized: '已授权', disclosed: '已公开', loaded: '已加载', invoked: '已调用', revoked: '已撤销' } as const)[value];
}

function layerLabel(value: CapabilityProjection['narrowedBy'][number]['layer']): string {
  return ({ authorization: '授权边界', 'agent-template': 'Agent 模板', 'collaboration-role': '协作岗位', 'collaboration-profile': '角色书', revocation: '撤销条件' } as const)[value];
}

function shortHash(value: string): string { return `${value.slice(0, 13)}…${value.slice(-7)}`; }
function safeId(value: string): string { return value.replace(/[^a-zA-Z0-9_-]/g, '-'); }
