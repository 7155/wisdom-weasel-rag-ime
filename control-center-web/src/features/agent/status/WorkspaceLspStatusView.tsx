import {
  CheckCircle2,
  CircleDashed,
  Clock3,
  RotateCcw,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Disclosure } from '@/components/primitives';
import type { AgentActivityProjection, AgentProjectionState } from '@/contracts/agent-reducer';
import { approvalNeedsHumanDecision } from '@/contracts/approval-decision';
import { validateContract } from '@/contracts/validators';
import type { WorkspaceLspStatusV1 } from '@/contracts/generated/workspace-lsp-status.v1';
import type { CapabilityCatalog } from '@/features/plugins/capability-policy';
import type { ToolManifest } from '../types';

const TOOL_ID = 'workspace_lsp';
const WRITE_OPERATIONS = new Set(['rename', 'code_action_apply']);

export type WorkspaceLspPresentationState =
  | 'checking'
  | 'available'
  | 'ready'
  | 'unavailable'
  | 'degraded'
  | 'approval_pending'
  | 'stale_refusal';

type WorkspaceLspServerState = 'available' | 'ready' | 'unavailable' | 'degraded';

type WorkspaceLspServerView = {
  name: string;
  state: WorkspaceLspServerState;
  languageIds: string[];
  fileExtensions: string[];
  errorCode: string;
  error: string;
};

type WorkspaceLspRootView = {
  errorCode: string;
  error: string;
  root: string;
  state: WorkspaceLspServerState;
  servers: WorkspaceLspServerView[];
};

export type WorkspaceLspPresentation = {
  state: WorkspaceLspPresentationState;
  label: string;
  summary: string;
  guidance: string;
  availability: ToolManifest['availability'] | 'unknown';
  roots: WorkspaceLspRootView[];
  serverCount: number;
  readyServerCount: number;
  failure?: { code: string; message: string };
};

export function WorkspaceLspStatusView({
  capabilityCatalog,
  catalogStatus,
  onRefresh,
  projection,
  tools,
}: {
  capabilityCatalog?: CapabilityCatalog;
  catalogStatus: 'loading' | 'ready' | 'failed';
  onRefresh?: () => void;
  projection?: AgentProjectionState;
  tools: ToolManifest[];
}) {
  const nowMs = useRuntimeProjectionClock(capabilityCatalog, onRefresh);
  const view = projectWorkspaceLspStatus(tools, catalogStatus, projection, capabilityCatalog, nowMs);
  const StateIcon = view.state === 'ready'
    ? CheckCircle2
    : view.state === 'approval_pending'
      ? Clock3
      : view.state === 'stale_refusal'
        ? RotateCcw
        : view.state === 'unavailable' || view.state === 'degraded'
          ? TriangleAlert
          : CircleDashed;

  return (
    <div className="agent-workspace-lsp" data-state={view.state}>
      <div className="agent-workspace-lsp__summary" role="status" aria-live="polite">
        <StateIcon size={15} aria-hidden="true" />
        <span>
          <strong><code>{TOOL_ID}</code> · {view.label}</strong>
          <small>{view.summary}</small>
        </span>
      </div>

      <p className="agent-workspace-lsp__guidance">
        <ShieldCheck size={15} aria-hidden="true" />
        <span><strong>下一步</strong>{view.guidance}</span>
      </p>
      {view.roots.length ? (
        <Disclosure className="agent-workspace-lsp__disclosure" contentClassName="agent-workspace-lsp__roots" summary={`查看 ${view.roots.length} 个活动工作区与 ${view.serverCount} 个语言服务器`}>
            {view.roots.map((root) => (
              <section key={root.root}>
                <header><code>{root.root}</code><span>{serverStateLabel(root.state)}</span></header>
                {root.errorCode || root.error ? (
                  <p>
                    {root.errorCode ? <code>{root.errorCode}</code> : null}
                    {root.error ? <span>{root.error}</span> : null}
                  </p>
                ) : null}
                {root.servers.length ? (
                  <ul>
                    {root.servers.map((server, index) => (
                      <li key={`${root.root}:${server.name}:${index}`} data-state={server.state}>
                        <span><strong>{server.name}</strong><small>{serverDetail(server)}</small></span>
                        <i>{serverStateLabel(server.state)}</i>
                        {server.errorCode || server.error ? (
                          <p>
                            {server.errorCode ? <code>{server.errorCode}</code> : null}
                            {server.error ? <span>{server.error}</span> : null}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : <p>该工作区没有 Runtime 报告的语言服务器。</p>}
              </section>
            ))}
        </Disclosure>
      ) : null}

      {view.failure ? (
        <Disclosure className="agent-workspace-lsp__disclosure" data-tone="danger" contentClassName="agent-workspace-lsp__failure" summary="查看失败信息">
          <p>
            {view.failure.code ? <code>{view.failure.code}</code> : null}
            {view.failure.message ? <span>{view.failure.message}</span> : null}
          </p>
        </Disclosure>
      ) : null}
    </div>
  );
}

export function projectWorkspaceLspStatus(
  tools: ToolManifest[],
  catalogStatus: 'loading' | 'ready' | 'failed',
  projection?: AgentProjectionState,
  capabilityCatalog?: CapabilityCatalog,
  nowMs = Date.now(),
): WorkspaceLspPresentation {
  const manifest = tools.find((tool) => tool.id === TOOL_ID);
  const activities = lspActivities(projection);
  const runtimeProjection = currentRuntimeProjection(capabilityCatalog, nowMs);
  const roots = runtimeProjection.kind === 'current' ? statusRoots(runtimeProjection.value) : [];
  const servers = roots.flatMap((root) => root.servers);
  const pendingWrite = [...activities].reverse().find(isPendingWriteApproval);
  const latestWrite = [...activities].reverse().find((activity) => WRITE_OPERATIONS.has(activityOperation(activity)));
  const staleFailure = latestWrite && isStaleRefusal(latestWrite) ? activityFailure(latestWrite) : undefined;

  if (catalogStatus === 'loading') {
    return presentation('checking', '正在确认', '正在从 Runtime 读取工具目录。',
      '等待目录返回；Control Center 不会自行启动语言服务器。', 'unknown', [], []);
  }
  if (catalogStatus === 'failed') {
    return presentation('unavailable', '无法确认', '工具目录暂时不可用，当前能力状态未知。',
      '等待连接恢复；重连后以新的工具目录与会话快照为准。', 'unknown', [], []);
  }
  if (!manifest) {
    return presentation('unavailable', '未公开', '当前 Session 的工具目录没有公开代码智能能力。',
      '检查 Session Tool 策略；公开能力不等于授权，策略变更会在下一次打开或回合生效。', 'unknown', roots, servers);
  }
  if (manifest.enabled === false) {
    return presentation('unavailable', '未启用', '当前 Session 的 Runtime 策略没有启用代码智能。',
      '在 Session Tool 策略中启用后，开始下一回合或重新打开会话以读取新目录。', manifest.availability, roots, servers);
  }
  if (manifest.availability !== 'online') {
    const copy = unavailableManifestCopy(manifest.availability);
    return presentation('unavailable', copy.label, copy.summary, copy.guidance,
      manifest.availability, roots, servers);
  }
  if (pendingWrite) {
    const operation = activityOperation(pendingWrite);
    return presentation('approval_pending', '待审批', `${writeOperationLabel(operation)}正在等待受管审批；确认前不会写入。`,
      '在当前回合的审批卡片中审阅预览；若文件已变化，请重新生成预览。', manifest.availability, roots, servers);
  }
  if (staleFailure) {
    return presentation('stale_refusal', '预览已失效', 'Runtime 拒绝了过期预览，没有写入文件。',
      '重新发起 rename 或代码动作，基于当前文件生成新的哈希绑定预览。', manifest.availability, roots, servers, staleFailure);
  }
  if (runtimeProjection.kind === 'missing') {
    return presentation('available', '可用 · 待确认', '能力目录没有当前 Runtime 投影；历史工具回执不代表当前状态。',
      '等待新的能力目录投影，或让 Agent 运行 workspace_lsp status。', manifest.availability, [], []);
  }
  if (runtimeProjection.kind === 'invalid') {
    return presentation('unavailable', '投影无效', 'Runtime 投影未通过前端契约检查，不能确认当前服务器状态。',
      '重新连接以读取新的能力目录；不要把历史工具回执视为当前状态。', manifest.availability, [], []);
  }
  if (runtimeProjection.kind === 'expired') {
    return presentation('available', '状态已过期', 'Runtime 投影的心跳已经过期，当前就绪状态未知。',
      '等待重连后的新能力目录；过期前的 root 与 server 状态不会继续展示。', manifest.availability, [], []);
  }
  if (runtimeProjection.kind === 'closed') {
    return presentation('unavailable', '运行已结束', 'Runtime 已撤销这份代码智能投影，当前没有活动服务器状态。',
      '重新打开会话或开始下一回合，以新的 Runtime 实例与 epoch 为准。', manifest.availability, [], []);
  }
  if (roots.length === 0) {
    const runtimeState = runtimeProjection.value.state;
    const summary = publicText(runtimeProjection.value.summary, 500);
    if (runtimeState === 'degraded' || runtimeState === 'unavailable') {
      return presentation(runtimeState, runtimeState === 'degraded' ? '降级' : '不可用',
        summary || 'Runtime 当前没有可展示的活动工作区。',
        failureGuidance(runtimeState === 'degraded' ? 'server_degraded' : 'server_unavailable'),
        manifest.availability, [], []);
    }
    return presentation('available', runtimeState === 'ready' ? '待确认' : '可用 · 尚未就绪',
      summary || 'Runtime 当前没有可展示的活动工作区。',
      '再次运行 workspace_lsp status；没有活动 root 时不会推断服务器就绪。', manifest.availability, [], []);
  }

  const readyCount = servers.filter((server) => server.state === 'ready').length;
  const readyRoots = roots.filter((root) => root.state === 'ready');
  const unavailableRoots = roots.filter((root) => root.state === 'unavailable');
  const degradedRoots = roots.filter((root) => root.state === 'degraded');
  const unavailableServers = servers.filter((server) => server.state === 'unavailable');
  const degradedServers = servers.filter((server) => server.state === 'degraded');
  const reportedFailure = [
    ...degradedRoots,
    ...unavailableRoots,
    ...degradedServers,
    ...unavailableServers,
  ].map((item) => ({ code: item.errorCode, message: item.error }))
    .find((failure) => failure.code || failure.message);

  if (
    runtimeProjection.value.state === 'degraded'
    || degradedRoots.length
    || degradedServers.length
    || (unavailableRoots.length > 0 && unavailableRoots.length < roots.length)
    || (unavailableServers.length > 0 && unavailableServers.length < servers.length)
  ) {
    return presentation('degraded', '降级', `${readyCount} / ${servers.length} 个语言服务器就绪。`,
      failureGuidance(reportedFailure?.code || 'server_degraded'), manifest.availability, roots, servers, reportedFailure);
  }
  if (
    runtimeProjection.value.state === 'unavailable'
    || unavailableRoots.length === roots.length
    || (servers.length > 0 && unavailableServers.length === servers.length)
  ) {
    return presentation('unavailable', '不可用', 'Runtime 报告的语言服务器均不可用。',
      failureGuidance(reportedFailure?.code || 'server_unavailable'), manifest.availability, roots, servers, reportedFailure);
  }
  if (
    runtimeProjection.value.state === 'ready'
    && servers.length > 0
    && readyCount === servers.length
    && readyRoots.length === roots.length
  ) {
    return presentation('ready', '就绪', `${readyCount} 个语言服务器覆盖 ${roots.length} 个活动工作区。`,
      '可使用只读代码智能；rename 与代码动作仍会先生成预览并等待审批。', manifest.availability, roots, servers);
  }
  return presentation('available', '可用 · 尚未就绪', `${servers.length} 个语言服务器已发现，Runtime 尚未全部报告 ready。`,
    '再次运行 workspace_lsp status；在 ready 之前不要把语义查询视为成功。', manifest.availability, roots, servers);
}

function presentation(
  state: WorkspaceLspPresentationState,
  label: string,
  summary: string,
  guidance: string,
  availability: WorkspaceLspPresentation['availability'],
  roots: WorkspaceLspRootView[],
  servers: WorkspaceLspServerView[],
  failure?: WorkspaceLspPresentation['failure'],
): WorkspaceLspPresentation {
  return {
    state,
    label,
    summary,
    guidance,
    availability,
    roots,
    serverCount: servers.length,
    readyServerCount: servers.filter((server) => server.state === 'ready').length,
    ...(failure && (failure.code || failure.message) ? { failure } : {}),
  };
}

type RuntimeProjectionResolution =
  | { kind: 'current'; value: WorkspaceLspStatusV1 }
  | { kind: 'missing' }
  | { kind: 'invalid' }
  | { kind: 'expired' }
  | { kind: 'closed' };

function currentRuntimeProjection(
  catalog: CapabilityCatalog | undefined,
  nowMs: number,
): RuntimeProjectionResolution {
  const validated = validatedCatalogRuntimeProjection(catalog);
  if (validated.kind !== 'valid') return validated;
  const projection = validated.value;
  if (!projection.current) return { kind: 'closed' };
  if (
    projection.heartbeatExpiresAtMs <= projection.observedAtMs
    || projection.heartbeatExpiresAtMs <= nowMs
  ) return { kind: 'expired' };
  return { kind: 'current', value: projection };
}

function useRuntimeProjectionClock(catalog?: CapabilityCatalog, onRefresh?: () => void): number {
  const [, renderAtExpiry] = useState(0);
  const refreshRef = useRef(onRefresh);
  const refreshedProjectionRef = useRef('');
  refreshRef.current = onRefresh;
  const validated = validatedCatalogRuntimeProjection(catalog);
  const projection = validated.kind === 'valid' ? validated.value : undefined;
  const runtimeInstanceId = projection?.runtimeInstanceId ?? '';
  const runtimeEpoch = projection?.runtimeEpoch ?? -1;
  const expiresAtMs = projection?.heartbeatExpiresAtMs ?? 0;
  const current = projection?.current === true;
  useEffect(() => {
    if (!current) {
      refreshedProjectionRef.current = '';
      return undefined;
    }
    const projectionKey = `${runtimeInstanceId}:${runtimeEpoch}:${expiresAtMs}`;
    const expire = () => {
      renderAtExpiry((revision) => revision + 1);
      if (refreshedProjectionRef.current === projectionKey) return;
      refreshedProjectionRef.current = projectionKey;
      refreshRef.current?.();
    };
    if (expiresAtMs <= Date.now()) {
      expire();
      return undefined;
    }
    const timer = window.setTimeout(expire, expiresAtMs - Date.now() + 1);
    return () => window.clearTimeout(timer);
  }, [current, expiresAtMs, runtimeEpoch, runtimeInstanceId]);
  return Date.now();
}

function validatedCatalogRuntimeProjection(catalog?: CapabilityCatalog):
  | { kind: 'valid'; value: WorkspaceLspStatusV1 }
  | { kind: 'missing' | 'invalid' } {
  const item = catalog?.items.find((candidate) => candidate.id === TOOL_ID);
  if (!item || item.runtimeProjection === undefined) return { kind: 'missing' };
  const validated = validateContract('workspace-lsp-status.v1', item.runtimeProjection);
  return validated.ok ? { kind: 'valid', value: validated.value } : { kind: 'invalid' };
}

function lspActivities(projection?: AgentProjectionState): AgentActivityProjection[] {
  if (!projection) return [];
  return projection.activityOrder
    .map((id) => projection.activitiesById[id])
    .filter((activity): activity is AgentActivityProjection => Boolean(activity && activityToolId(activity) === TOOL_ID));
}

function activityToolId(activity: AgentActivityProjection): string {
  const payload = activity.payload;
  const carrier = record(payload.result ?? payload.partialResult);
  const domain = record(carrier.result);
  const approval = record(payload.approval ?? domain.approval ?? carrier.approval);
  return firstText([payload, carrier, domain, approval], ['toolId', 'toolName', 'tool']).toLowerCase();
}

function activityOperation(activity: AgentActivityProjection): string {
  const payload = activity.payload;
  const carrier = record(payload.result ?? payload.partialResult);
  const domain = record(carrier.result);
  const approval = record(payload.approval ?? domain.approval ?? carrier.approval);
  return firstText([payload, carrier, domain, approval, record(payload.args)], ['operation']).toLowerCase();
}

function statusRoots(status: WorkspaceLspStatusV1): WorkspaceLspRootView[] {
  return status.roots.slice(0, 32).map((root) => ({
    root: publicText(root.root, 1_000),
    state: root.state,
    errorCode: publicText(root.errorCode, 120),
    error: publicText(root.error, 500),
    servers: root.servers.slice(0, 32).map((server) => ({
      name: publicText(server.name, 120),
      state: server.state,
      languageIds: publicStringArray(server.languageIds, 12),
      fileExtensions: publicStringArray(server.fileExtensions, 16),
      errorCode: publicText(server.errorCode, 120),
      error: publicText(server.error, 500),
    })).filter((server) => server.name),
  })).filter((root) => root.root);
}

function isPendingWriteApproval(activity: AgentActivityProjection): boolean {
  if (activity.status !== 'waiting' || !approvalNeedsHumanDecision(activity.payload) || !WRITE_OPERATIONS.has(activityOperation(activity))) return false;
  const payload = activity.payload;
  const carrier = record(payload.result ?? payload.partialResult);
  const domain = record(carrier.result);
  return activity.kind === 'approval_required'
    || payload.approvalRequired === true
    || carrier.approvalRequired === true
    || domain.approvalRequired === true;
}

function isStaleRefusal(activity: AgentActivityProjection): boolean {
  if (activity.status !== 'failed') return false;
  const failure = activityFailure(activity);
  return Boolean(failure && (
    failure.code === 'stale_snapshot'
    || failure.message.includes('workspace_lsp file changed after approval preview')
  ));
}

function activityFailure(activity: AgentActivityProjection): { code: string; message: string } | undefined {
  const payload = activity.payload;
  const carrier = record(payload.result ?? payload.partialResult);
  const domain = record(carrier.result);
  const code = firstText([domain, carrier, payload], ['errorCode', 'code']);
  const message = publicText(firstValue([domain, carrier, payload], ['error', 'message']), 500);
  return code || message ? { code, message } : undefined;
}

function unavailableManifestCopy(availability: ToolManifest['availability']) {
  if (availability === 'disabled') return {
    label: '已停用', summary: '当前 Session 的 Runtime 策略已停用代码智能。',
    guidance: '在 Session Tool 策略中启用后，开始下一回合或重新打开会话以读取新目录。',
  };
  if (availability === 'unconfigured') return {
    label: '未配置', summary: 'Runtime 尚未配置 workspace_lsp。',
    guidance: '配置匹配项目语言的服务器，再运行 workspace_lsp status。',
  };
  return {
    label: '离线', summary: 'Runtime 报告 workspace_lsp 当前离线。',
    guidance: '检查 Runtime 连接与语言服务器配置，再运行 workspace_lsp status。',
  };
}

function failureGuidance(code: string): string {
  if (code === 'no_server_configured') return '安装并配置匹配项目语言的服务器，再运行 workspace_lsp status。';
  if (code === 'request_timeout') return '重新运行 status；若持续超时，请检查语言服务器日志与项目规模。';
  if (code === 'request_cancelled') return '请求已取消；需要时重新运行 workspace_lsp status。';
  if (code === 'server_degraded') return '查看公开失败信息，修复服务后重新运行 status；写操作不会自行继续。';
  return '检查语言服务器安装与配置，再运行 workspace_lsp status。';
}

function writeOperationLabel(operation: string): string {
  return operation === 'rename' ? '重命名预览' : '代码动作预览';
}

function serverStateLabel(state: WorkspaceLspServerState): string {
  return ({ available: '可用', ready: '就绪', unavailable: '不可用', degraded: '降级' })[state];
}

function serverDetail(server: WorkspaceLspServerView): string {
  const languages = server.languageIds.length ? server.languageIds.join('、') : '未报告语言';
  const extensions = server.fileExtensions.length ? server.fileExtensions.join('、') : '未报告扩展名';
  return `${languages} · ${extensions}`;
}

function publicStringArray(value: unknown, limit: number): string[] {
  return Array.isArray(value)
    ? value.slice(0, limit).map((item) => publicText(item, 80)).filter(Boolean)
    : [];
}

function publicText(value: unknown, limit: number): string {
  return text(value).replace(/[\u0000-\u001f\u007f]/gu, ' ').replace(/\s+/gu, ' ').trim().slice(0, limit);
}

function firstText(layers: Record<string, unknown>[], keys: string[]): string {
  return text(firstValue(layers, keys));
}

function firstValue(layers: Record<string, unknown>[], keys: string[]): unknown {
  for (const layer of layers) {
    for (const key of keys) {
      if (layer[key] !== undefined && layer[key] !== null) return layer[key];
    }
  }
  return undefined;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
