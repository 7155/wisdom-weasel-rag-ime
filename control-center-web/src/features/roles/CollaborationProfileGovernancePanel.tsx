import { FileDiff, Fingerprint, LockKeyhole, ReceiptText, RotateCcw, ShieldCheck, ShieldX } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { Button } from '@/components/primitives';
import type { CollaborationProfileCommandReceiptV1 } from '@/contracts/generated/collaboration-profile-command-receipt.v1';
import type { CollaborationProfileCommandV1 } from '@/contracts/generated/collaboration-profile-command.v1';
import type { CollaborationProfileProjectionV1 } from '@/contracts/generated/collaboration-profile-projection.v1';
import { parseContract } from '@/contracts/validators';
import type { JsonValue } from '@/platform/transport';
import { evaluateCollaborationProfileControlGate, type CollaborationProfileControlGate } from './collaboration-profile-control-gate';
import './collaboration-profile-governance.css';

type Action = CollaborationProfileCommandV1['action'];
type OperationStatus = 'idle' | 'pending' | 'applied' | 'rejected' | 'unknown';

export function CollaborationProfileGovernancePanel({ profileId }: { profileId: string }) {
  const transport = useControlTransport();
  const [projection, setProjection] = useState<CollaborationProfileProjectionV1 | null>(null);
  const [gate, setGate] = useState<CollaborationProfileControlGate | null>(null);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'missing' | 'denied' | 'error'>('loading');
  const [notice, setNotice] = useState('正在读取 canonical Profile projection');
  const [bundleText, setBundleText] = useState('');
  const [candidate, setCandidate] = useState<{ candidateId: string; contentHash: string; stage: string; signerId: string } | null>(null);
  const [activationScope, setActivationScope] = useState<'immediate' | 'new_roots_only'>('new_roots_only');
  const [operation, setOperation] = useState<{ action: Action | null; status: OperationStatus; message: string; receipt: CollaborationProfileCommandReceiptV1 | null }>({ action: null, status: 'idle', message: '', receipt: null });
  const pendingRef = useRef(false);

  const load = useCallback(async () => {
    setLoadState('loading');
    try {
      const capabilities = await transport.capabilities();
      const initialGate = await evaluateCollaborationProfileControlGate(capabilities);
      setGate(initialGate);
      if (!initialGate.readEnabled) {
        setLoadState('denied');
        setNotice(initialGate.reason);
        return;
      }
      const value = await transport.request<CollaborationProfileProjectionV1>({
        pathId: 'agent.collaborationProfile.get', params: { profileId },
        responseContract: 'collaboration-profile-projection.v1',
      });
      const next = parseContract('collaboration-profile-projection.v1', value);
      if (next.profileId !== profileId) throw new TypeError('CollaborationProfile projection belongs to another profile');
      const verifiedGate = await evaluateCollaborationProfileControlGate(capabilities, next.routeHash);
      setGate(verifiedGate);
      setProjection(next);
      setLoadState('ready');
      setNotice(verifiedGate.commandEnabled ? 'canonical projection 已同步' : verifiedGate.reason);
    } catch (error) {
      const status = errorStatus(error);
      setProjection(null);
      setLoadState(status === 404 ? 'missing' : status === 401 || status === 403 ? 'denied' : 'error');
      setNotice(status === 404 ? '该角色书尚未安装；普通 Agent 和无 Room Agent 不受影响。' : publicError(error));
    }
  }, [profileId, transport]);

  useEffect(() => { void load(); }, [load]);

  const inspection = useMemo(() => normalizeInspection(projection?.inspection), [projection]);
  const receipts = useMemo(() => normalizeReceipts(projection?.recentReceipts ?? []), [projection]);
  const manifest = inspection.active?.manifest ?? inspection.versions[0]?.manifest ?? null;
  const compile = latestResult(receipts, 'compile');
  const validateObserved = receipts.some((receipt) => receipt.action === 'validate');
  const diff = capabilityDiff(compile);
  const activeRootIds = stringArray(latestResult(receipts, 'activate')?.affectedRootIds);
  const writeEnabled = gate?.commandEnabled === true && loadState === 'ready';

  async function execute(action: Action) {
    if (!writeEnabled || pendingRef.current) return;
    let parsedBundle: Record<string, unknown> | undefined;
    if (action === 'inspect') {
      try {
        const parsed = JSON.parse(bundleText);
        if (!isRecord(parsed)) throw new TypeError('bundle must be an object');
        parsedBundle = parsed;
      } catch (error) {
        setOperation({ action, status: 'rejected', message: `Bundle JSON 无效：${publicError(error)}`, receipt: null });
        return;
      }
    }
    const sensitive = action === 'activate' || action === 'rollback' || action === 'revoke';
    if (sensitive && !window.confirm(`${actionLabel(action)}会改变角色书指针或撤销状态。确认以管理员身份继续？`)) return;
    pendingRef.current = true;
    setOperation({ action, status: 'pending', message: '命令已提交，等待类型化回执', receipt: null });
    try {
      const command = buildCommand({
        action, profileId, candidate, inspection, activationScope,
        bundle: parsedBundle,
      });
      const receipt = await transport.request<CollaborationProfileCommandReceiptV1>({
        pathId: 'agent.collaborationProfile.command', body: command as unknown as JsonValue,
        responseContract: 'collaboration-profile-command-receipt.v1',
      });
      await verifyReceipt(receipt, command, projection);
      const result = isRecord(receipt.result) ? receipt.result : {};
      const candidateId = text(result.candidateId);
      const contentHash = text(result.contentHash);
      if (candidateId && contentHash) {
        setCandidate({
          candidateId, contentHash, stage: text(result.stage) || action,
          signerId: action === 'inspect' ? text(isRecord(parsedBundle?.signature) ? parsedBundle.signature.signerId : '') : candidate?.signerId ?? '',
        });
      }
      setOperation({ action, status: 'applied', message: receiptMessage(receipt), receipt });
      await load();
    } catch (error) {
      const status = errorStatus(error);
      setOperation({
        action,
        status: status > 0 && status < 500 ? 'rejected' : 'unknown',
        message: failureMessage(error),
        receipt: null,
      });
    } finally {
      pendingRef.current = false;
    }
  }

  return <section className="profile-governance" aria-label="角色书正式控制面" data-load-state={loadState}>
    <header><span><LockKeyhole size={14} /><strong>正式控制面</strong></span><small>{projection ? `guard epoch ${projection.guardEpoch}` : loadStateLabel(loadState)}</small></header>
    <p className="profile-governance__notice" role={loadState === 'denied' || loadState === 'error' ? 'alert' : 'status'}>{notice}</p>
    {projection?.normalAgentFallback ? <p className="profile-governance__fallback">普通 Agent 和无 Room Agent 不受影响；只有显式绑定该 Profile 的新 Root 才读取活动指针。</p> : null}
    {projection ? <>
      <dl>
        <div><dt><Fingerprint size={14} />Profile route</dt><dd title={projection.routeHash}>{shortHash(projection.routeHash)}</dd></div>
        <div><dt>Pointer revision</dt><dd>r{inspection.pointerRevision}</dd></div>
        <div><dt><Fingerprint size={14} />Active hash</dt><dd title={inspection.active?.contentHash}>{shortHash(inspection.active?.contentHash || '未启用')}</dd></div>
        <div><dt><ShieldCheck size={14} />Signature</dt><dd>{candidate?.signerId ? `${candidate.signerId} · ${candidate.stage}` : manifest ? `${text(manifest.trustTier)} · ${validateObserved ? 'validate 回执已观察' : '签名回执未上报'}` : '未上报'}</dd></div>
        <div><dt><ReceiptText size={14} />Compile receipt</dt><dd>{inspection.active?.compileReceiptId || text(compile?.receiptId) || '未上报'}</dd></div>
        <div><dt>Binding revision</dt><dd>{inspection.active?.bindingRevision || text(compile?.bindingRevision) || '未上报'}</dd></div>
      </dl>
      <section className="profile-governance__manifest" aria-label="角色书声明">
        <header><strong>{text(manifest?.displayName) || profileId}</strong><small>{text(manifest?.version) ? `v${text(manifest?.version)}` : '没有活动版本'}</small></header>
        <p>{text(manifest?.summary) || '当前 projection 没有活动 manifest。'}</p>
        <pre tabIndex={0} aria-label="角色书提示词只读文本">{stringArray(manifest?.promptGuidance).join('\n') || '未上报提示词指导'}</pre>
      </section>
      <ol aria-label="角色书安全流水线">{(['inspect', 'validate', 'compile', 'dry_run', 'stage', 'activate'] as Action[]).map((action) => <li key={action} data-state={pipelineState(action, receipts, candidate)}>{actionLabel(action)}</li>)}</ol>
      <section className="profile-governance__diff" aria-label="角色书能力差异">
        <header><span><FileDiff size={14} /><strong>能力差异</strong></span><small>compile receipt 投影</small></header>
        <p><b>基线</b><span>{diff.baseline.join(' · ') || '未上报'}</span></p>
        <p><b>有效</b><span>{diff.effective.join(' · ') || '未上报'}</span></p>
        <p data-change="removed"><b>收窄</b><span>{diff.removed.join(' · ') || '无变化'}</span></p>
        <p data-change="blocked"><b>拒绝</b><span>{diff.rejected.join(' · ') || '无'}</span></p>
      </section>
      <section className="profile-governance__pointer" aria-label="角色书指针控制">
        <header><strong>指针控制</strong><small>new-roots-only 默认保护活动 Root</small></header>
        <label><input type="checkbox" checked={activationScope === 'new_roots_only'} onChange={(event) => setActivationScope(event.target.checked ? 'new_roots_only' : 'immediate')} />仅新 Root 使用</label>
        <p>{activeRootIds.length ? `活动 Root blocker：${activeRootIds.join(' · ')}` : '当前 projection 未上报活动 Root blocker。immediate 仍由后端最终裁决。'}</p>
      </section>
      <section className="profile-governance__candidate" aria-label="角色书候选包">
        <label htmlFor={`profile-bundle-${profileId}`}>声明式 Profile bundle JSON</label>
        <textarea id={`profile-bundle-${profileId}`} value={bundleText} onChange={(event) => setBundleText(event.target.value)} disabled={!writeEnabled || operation.status === 'pending'} rows={5} />
      </section>
      <div className="profile-governance__actions" aria-label="角色书流水线命令">
        {(['inspect', 'validate', 'compile', 'dry_run', 'stage'] as Action[]).map((action) => <Button key={action} variant="quiet" size="small" disabled={!writeEnabled || operation.status === 'pending' || !actionReady(action, candidate, bundleText)} onClick={() => void execute(action)}>{actionLabel(action)}</Button>)}
        <Button variant="primary" size="small" disabled={!writeEnabled || operation.status === 'pending' || !candidate || candidate.stage !== 'staged'} onClick={() => void execute('activate')}>启用</Button>
        <Button variant="quiet" size="small" leadingIcon={<RotateCcw size={12} />} disabled={!writeEnabled || operation.status === 'pending' || !inspection.active} onClick={() => void execute('rollback')}>回滚</Button>
        <Button variant="quiet" size="small" leadingIcon={<ShieldX size={12} />} disabled={!writeEnabled || operation.status === 'pending' || !inspection.active} onClick={() => void execute('revoke')}>撤销</Button>
      </div>
      <OperationReceipt operation={operation} />
      <section className="profile-governance__receipts" aria-label="角色书最近回执"><header><strong>最近类型化回执</strong><small>{receipts.length} 项</small></header>{receipts.length ? receipts.map((receipt) => <p key={receipt.receiptId}><span><b>{actionLabel(receipt.action)}</b><small>{receipt.receiptId}</small></span><span><b data-status="applied">applied</b><small>epoch {receipt.guardEpoch} · {shortHash(receipt.commandHash)}</small></span></p>) : <p>暂无回执。</p>}</section>
    </> : loadState === 'missing' ? <p className="profile-governance__fallback">普通 Agent、无 Profile Agent 和无 Room Agent 继续使用原有运行路径，不会被角色书控制面阻断。</p> : null}
  </section>;
}

function OperationReceipt({ operation }: { operation: { action: Action | null; status: OperationStatus; message: string; receipt: CollaborationProfileCommandReceiptV1 | null } }) {
  if (operation.status === 'idle') return null;
  return <p className="profile-governance__operation" role={operation.status === 'rejected' || operation.status === 'unknown' ? 'alert' : 'status'} data-status={operation.status}><strong>{operation.action ? actionLabel(operation.action) : '命令'} · {operation.status}</strong><span>{operation.message}</span>{operation.receipt ? <small>{operation.receipt.receiptId} · epoch {operation.receipt.guardEpoch}</small> : null}</p>;
}

function buildCommand(input: { action: Action; profileId: string; candidate: { candidateId: string; contentHash: string; stage: string } | null; inspection: Inspection; activationScope: 'immediate' | 'new_roots_only'; bundle?: Record<string, unknown> }): CollaborationProfileCommandV1 {
  const now = Date.now();
  const command: CollaborationProfileCommandV1 = {
    schemaVersion: 'rag-ime.collaboration-profile-command.v1', commandId: `profile-command:ui:${input.action}:${now}`,
    action: input.action, idempotencyKey: `profile-ui:${input.action}:${now}`, actorRef: 'control-center:administrator', payload: {}, createdAtMs: now,
  };
  if (input.action === 'inspect') command.payload = { bundle: input.bundle };
  if (['validate', 'compile', 'dry_run', 'stage'].includes(input.action)) command.candidateId = input.candidate?.candidateId;
  if (input.action === 'activate') {
    command.profileId = input.profileId; command.contentHash = input.candidate?.contentHash;
    command.expectedPointerRevision = input.inspection.pointerRevision; command.activationScope = input.activationScope;
    command.adminConfirmation = 'ACTIVATE PROFILE';
  }
  if (input.action === 'rollback') {
    command.profileId = input.profileId; command.expectedPointerRevision = input.inspection.pointerRevision;
    command.adminConfirmation = 'ROLLBACK PROFILE';
  }
  if (input.action === 'revoke') {
    command.contentHash = input.inspection.active?.contentHash; command.expectedPointerRevision = input.inspection.pointerRevision;
    command.adminConfirmation = 'REVOKE PROFILE'; command.payload = { reason: 'administrator revoked from Control Center' };
  }
  return command;
}

async function verifyReceipt(receipt: CollaborationProfileCommandReceiptV1, command: CollaborationProfileCommandV1, projection: CollaborationProfileProjectionV1 | null) {
  if (receipt.commandId !== command.commandId || receipt.action !== command.action) throw new TypeError('Profile receipt does not match the submitted command');
  if (receipt.commandHash !== await hashCommand(command)) throw new TypeError('Profile receipt command hash mismatch');
  if (projection && receipt.routeHash !== projection.routeHash) throw new TypeError('Profile receipt route hash mismatch');
  if (projection && receipt.guardEpoch < projection.guardEpoch) throw new TypeError('Profile receipt guard epoch is stale');
}

async function hashCommand(value: CollaborationProfileCommandV1): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalJson(value)));
  return `sha256:${Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, '0')).join('')}`;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (isRecord(value)) return `{${Object.keys(value).filter((key) => value[key] !== undefined).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  return JSON.stringify(value) ?? 'null';
}

type Inspection = { pointerRevision: number; active: Version | null; versions: Version[] };
type Version = { contentHash: string; version: string; compileReceiptId: string; bindingRevision: string; manifest: Record<string, unknown>; revoked: boolean };
function normalizeInspection(value: unknown): Inspection {
  const item = isRecord(value) ? value : {};
  const versions = Array.isArray(item.versions) ? item.versions.map(normalizeVersion).filter((entry): entry is Version => Boolean(entry)) : [];
  const activeRaw = isRecord(item.active) ? item.active : null;
  const activeHash = text(activeRaw?.contentHash);
  const version = versions.find((entry) => entry.contentHash === activeHash);
  return { pointerRevision: integer(item.pointerRevision), active: activeRaw ? { contentHash: activeHash, version: text(activeRaw.version), compileReceiptId: text(activeRaw.compileReceiptId), bindingRevision: text(activeRaw.bindingRevision), manifest: version?.manifest ?? {}, revoked: false } : null, versions };
}
function normalizeVersion(value: unknown): Version | null { const item = isRecord(value) ? value : {}; const hash = text(item.contentHash); return hash ? { contentHash: hash, version: text(item.version), compileReceiptId: text(item.compileReceiptId), bindingRevision: '', manifest: isRecord(item.manifest) ? item.manifest : {}, revoked: item.revoked === true } : null; }
function normalizeReceipts(values: Record<string, unknown>[]): CollaborationProfileCommandReceiptV1[] { return values.flatMap((value) => { try { return [parseContract('collaboration-profile-command-receipt.v1', value)]; } catch { return []; } }); }
function latestResult(receipts: CollaborationProfileCommandReceiptV1[], action: Action): Record<string, unknown> | null { const receipt = receipts.find((item) => item.action === action); return receipt && isRecord(receipt.result) ? receipt.result : null; }
function capabilityDiff(result: Record<string, unknown> | null) { const baseline = stringArray(result?.baselineCapabilities); const effective = stringArray(result?.effectiveCapabilities); return { baseline, effective, removed: baseline.filter((item) => !effective.includes(item)), rejected: stringArray(result?.rejectedCapabilities) }; }
function pipelineState(action: Action, receipts: CollaborationProfileCommandReceiptV1[], candidate: { stage: string } | null) {
  const target = ({ inspect: 'inspected', validate: 'validated', compile: 'compiled', dry_run: 'dry_run', stage: 'staged', activate: 'activate' } as Record<string, string>)[action];
  return receipts.some((item) => item.action === action) || candidateStageIndex(candidate?.stage) >= candidateStageIndex(target) ? 'applied' : 'pending';
}
function actionReady(action: Action, candidate: { stage: string } | null, bundleText: string) { if (action === 'inspect') return Boolean(bundleText.trim()); const expected = ({ validate: 'inspected', compile: 'validated', dry_run: 'compiled', stage: 'dry_run' } as Record<string, string>)[action]; return candidate?.stage === expected; }
function candidateStageIndex(value?: string) { return ['inspected', 'validated', 'compiled', 'dry_run', 'staged', 'activate'].indexOf(value || ''); }
function actionLabel(value: Action) { return ({ inspect: '检查', validate: '校验签名', compile: '编译', dry_run: '试运行', stage: '暂存', activate: '启用', rollback: '回滚', revoke: '撤销' } as const)[value]; }
function receiptMessage(receipt: CollaborationProfileCommandReceiptV1) { const result = isRecord(receipt.result) ? receipt.result : {}; return `applied · pointer r${integer(result.pointerRevision)} · ${text(result.activationScope) || 'pipeline'}`; }
function failureMessage(error: unknown) { const message = publicError(error); if (/pointer revision changed/i.test(message)) return `stale revision：${message}`; if (/hash|signature/i.test(message)) return `hash/signature mismatch：${message}`; if (/active Root pins/i.test(message)) return `active Root blocker：${message}`; return message; }
function loadStateLabel(value: string) { return ({ loading: '读取中', ready: '已同步', missing: '未安装', denied: '无权限', error: '读取失败' } as Record<string, string>)[value] ?? value; }
function publicError(error: unknown) { return error instanceof Error && error.message ? error.message : 'Profile command result is unknown'; }
function errorStatus(error: unknown) { return isRecord(error) && typeof error.status === 'number' ? error.status : 0; }
function shortHash(value: string) { return value.length > 24 ? `${value.slice(0, 15)}…${value.slice(-8)}` : value; }
function text(value: unknown) { return typeof value === 'string' ? value : ''; }
function integer(value: unknown) { return Number.isInteger(value) ? Number(value) : 0; }
function stringArray(value: unknown) { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []; }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
