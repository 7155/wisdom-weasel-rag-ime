import { Activity, Clipboard, Cpu, Keyboard, RefreshCw, ServerCog } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, Disclosure, EmptyState } from '@/components/primitives';
import { writeClipboardText } from '@/platform/clipboard';
import { useDiagnosticsQueries } from './api';
import { DiagnosticsRuntimeWorkflow, type DiagnosticsRuntimeAction } from './runtime-actions';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  asRecord,
  booleanValue,
  numberValue,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import './diagnostics.css';

export function DiagnosticsFeature() {
  const queries = useDiagnosticsQueries();
  const runtime = asRecord(queries.runtime.data);
  const predictorEnvelope = asRecord(queries.predictor.data);
  const predictor = asRecord(predictorEnvelope.predictor);
  const predictorProbe = asRecord(predictor.capabilityProbe);
  const predictorCapabilities = asRecord(predictor.capabilities ?? predictorProbe.capabilities);
  const predictorModelInfo = asRecord(predictor.modelInfo ?? predictorProbe.modelInfo);
  const predictorProvider = stringValue(
    predictor.provider,
    stringValue(predictor.providerName, stringValue(predictor.kind, 'local')),
  );
  const predictorDimensions = numberValue(
    predictor.dimensions,
    numberValue(predictorCapabilities.dimensions, numberValue(predictorModelInfo.hiddenSize)),
  );
  const models = asRecord(queries.models.data);
  const inputSource = asRecord(queries.source.data);
  const components = Object.entries(asRecord(runtime.components)).map(([id, value]) => ({
    ...asRecord(value),
    id,
  } as Record<string, unknown>));
  const componentById = Object.fromEntries(components.map((item) => [stringValue(item.id), item]));
  const candidateDelivery = asRecord(componentById.assistantCandidateDelivery);
  const candidateStages = asRecord(asRecord(candidateDelivery.metadata).stages);
  const foregroundContext = asRecord(componentById.foregroundContext);
  const foregroundEvidence = asRecord(foregroundContext.metadata);
  const [copyStatus, setCopyStatus] = useState('');
  const runtimeRevision = numberValue(runtime.runtimeRevision, -1);
  const aiEnabled = booleanValue(asRecord(asRecord(runtime.runtimeConfig).postCommit).enabled, true);
  const repairActions = runtimeActions(aiEnabled);
  const capabilityKnown = queries.capabilities.data !== undefined;
  const canOpenAccessibilitySettings = Boolean(
    capabilityKnown
      && queries.capabilities.data?.native.approvedExternalActions
      && queries.transport.runApprovedExternalAction,
  );
  const error = [queries.runtime.error, queries.predictor.error, queries.models.error, queries.source.error].find(Boolean) as Error | null;
  const pending = queries.runtime.isPending || queries.predictor.isPending || queries.models.isPending || queries.source.isPending;
  const coreFetching = queries.runtime.isFetching
    || queries.predictor.isFetching
    || queries.models.isFetching
    || queries.source.isFetching;
  const reportReady = !error
    && [queries.runtime.data, queries.predictor.data, queries.models.data, queries.source.data]
      .every((value) => value !== undefined);
  const refresh = () => void Promise.all([
    queries.runtime.refetch(),
    queries.predictor.refetch(),
    queries.models.refetch(),
    queries.source.refetch(),
    queries.capabilities.refetch(),
  ]);
  const report = useMemo(() => JSON.stringify({
    runtime: redact(runtime),
    predictor: redact(predictorEnvelope),
    models: redact(models),
    inputSource: redact(inputSource),
  }, null, 2), [inputSource, models, predictorEnvelope, runtime]);

  const copyReport = async () => {
    try {
      await writeClipboardText(report);
      setCopyStatus('诊断快照已复制');
    } catch {
      setCopyStatus('当前环境不支持复制');
    }
  };

  return (
    <ManagementPage
      actions={
        <>
          <Button disabled={!reportReady} leadingIcon={<Clipboard size={15} />} onClick={() => void copyReport()} size="small">复制排查报告</Button>
          <Button leadingIcon={<RefreshCw size={15} />} loading={coreFetching || queries.capabilities.isFetching} onClick={refresh} size="small">刷新</Button>
        </>
      }
      description="哪里没准备好、为什么没准备好，以及下一步怎么处理，都从这里查。"
      eyebrow="帮你找问题"
      routeId="diagnostics"
      title="问题排查"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        {copyStatus ? <InlineNotice title="诊断导出" tone="info">{copyStatus}</InlineNotice> : null}
        {queries.capabilities.error ? (
          <div className="diagnostics-capability-state">
            <InlineNotice title="无法确认本机操作能力" tone="danger">
              当前无法判断是否能打开系统设置或执行本机修复。状态恢复前不会把它误报为“桌面端不可用”。
            </InlineNotice>
            <Button
              loading={queries.capabilities.isFetching}
              onClick={() => void queries.capabilities.refetch()}
              size="small"
            >
              重新检查操作能力
            </Button>
          </div>
        ) : null}
        <ManagementSection title="关键检查">
          <MetricStrip items={[
            { label: '输入法', value: booleanValue(inputSource.typingReady) ? '可以输入' : '需要检查', detail: inputReadinessLabel(stringValue(inputSource.readinessState)), icon: Keyboard, tone: booleanValue(inputSource.typingReady) ? 'success' : 'warning' },
            { label: '本机预测', value: booleanValue(predictorEnvelope.ok) ? '运行正常' : '需要检查', detail: predictorServiceLabel(predictorProvider), icon: Cpu, tone: booleanValue(predictorEnvelope.ok) ? 'success' : 'warning' },
            { label: '智能候选', value: booleanValue(candidateDelivery.ok) ? '已显示' : '等待前台验证', detail: '在真实应用中输入后刷新本页', icon: Activity, tone: booleanValue(candidateDelivery.ok) ? 'success' : 'warning' },
            {
              label: '系统设置',
              value: queries.capabilities.isPending
                ? '正在检查'
                : queries.capabilities.error ? '状态未知' : canOpenAccessibilitySettings ? '可以打开' : '当前不可用',
              detail: queries.capabilities.error ? '重新检查后确认' : 'macOS 辅助功能',
              icon: ServerCog,
              tone: queries.capabilities.isPending || queries.capabilities.error
                ? 'neutral'
                : canOpenAccessibilitySettings ? 'success' : 'warning',
            },
          ]} />
        </ManagementSection>

        {Object.keys(candidateDelivery).length ? (
          <ManagementSection
            title="智能候选检查"
            description="本机服务正常不代表候选已经显示。请依次检查输入法、已安装组件、本机补全服务、候选生成和前台显示。"
            trailing={<StatusBadge label={booleanValue(candidateDelivery.ok) ? '前台已验收' : '尚未前台验收'} tone={booleanValue(candidateDelivery.ok) ? 'success' : 'warning'} />}
          >
            <OperationalList items={candidateStageItems(candidateStages)} />
            {!booleanValue(asRecord(candidateStages.foregroundRendered).ok) ? (
              <InlineNotice title="还没有确认候选显示" tone="warning">
                先在真实应用中输入并等待智能候选，再刷新本页。若“候选已生成”但仍未显示，请在统一发布验收中重新部署受管输入法、重启输入法并复测；这类会改变已安装输入法的操作才需要确认，本页不会自行安装或重启。
              </InlineNotice>
            ) : null}
          </ManagementSection>
        ) : (
          <ManagementSection title="智能候选检查" description="候选是否真正显示，需要来自真实应用的前台验证记录。">
            <EmptyState
              action={<Button onClick={refresh} size="small">重新检查</Button>}
              description="暂未收到前台验证记录。请在真实应用中输入并等待智能候选出现，再重新检查。"
              headingLevel={3}
              icon={Activity}
              title="等待前台验证"
            />
          </ManagementSection>
        )}

        <ManagementSection title="服务状态" trailing={<StatusBadge label={`${components.length} 项`} tone={components.length ? (components.every((item) => booleanValue(item.ok)) ? 'success' : 'warning') : 'neutral'} />}>
          {components.length ? <DiagnosticsServiceList components={components} /> : <EmptyState action={<Button onClick={refresh} size="small">重新检查</Button>} description="暂未收到本机服务状态。" headingLevel={3} icon={Activity} title="暂无服务状态" />}
        </ManagementSection>

        <div className="mgmt-grid-2">
          <ManagementSection title="本机预测">
            <dl className="mgmt-kv">
              <dt>当前模型</dt><dd>{displayModelName(predictor)}</dd>
              <dt>可用状态</dt><dd>{booleanValue(predictorEnvelope.ok) ? '可以生成智能候选' : '需要查看服务状态或尝试修复'}</dd>
              <dt>下一步</dt><dd>{booleanValue(predictorEnvelope.ok) ? '在真实应用中输入，确认候选是否显示。' : '先查看服务状态；必要时重启本机补全服务。'}</dd>
            </dl>
          </ManagementSection>
          <ManagementSection title="模型路由">
            <dl className="mgmt-kv">
              <dt>本机预测</dt><dd>{booleanValue(models.ok) ? '可用' : '需要检查'}</dd>
              <dt>深度生成</dt><dd>{booleanValue(asRecord(models.activeRagRoute).remoteReady) ? '已连接' : '尚未连接'}</dd>
              <dt>当前状态</dt><dd>{routeStateLabel(stringValue(asRecord(models.activeRagRoute).skipReason))}</dd>
            </dl>
          </ManagementSection>
        </div>

        <DiagnosticsDisclosure className="diagnostics-boundary" summary="高级：诊断详情">
          <div className="mgmt-grid-2">
            <ManagementSection title="本机预测证据">
              <dl className="mgmt-kv">
                <dt>服务方式</dt><dd>{predictorServiceLabel(predictorProvider)}</dd>
                <dt>配置状态</dt><dd>{booleanValue(predictor.configured) ? '应启用' : '未配置'}</dd>
                <dt>连接探测</dt><dd>{booleanValue(predictorProbe.modelLoaded) ? '模型已加载' : booleanValue(predictorProbe.ok) ? '探测通过，未报告加载状态' : '未取得加载凭证'}</dd>
                <dt>运行位置</dt><dd>{runtimeLabel(stringValue(predictor.runtime, 'local'))}</dd>
                <dt>模型指纹</dt><dd>{fingerprintLabel(stringValue(predictorProbe.modelFingerprint))}</dd>
                <dt>缓存状态</dt><dd>{booleanValue(asRecord(predictor.statusCache).hit) ? '已命中' : '暂无命中'}</dd>
                <dt>模型维度</dt><dd>{predictorDimensions}</dd>
              </dl>
            </ManagementSection>
            <ManagementSection title="前台验证证据">
              <dl className="mgmt-kv">
                <dt>采集来源</dt><dd>{foregroundSourceLabel(stringValue(foregroundEvidence.source))}</dd>
                <dt>证据新鲜度</dt><dd>{freshnessLabel(numberValue(foregroundEvidence.freshnessMs, -1))}</dd>
                <dt>已写入当前应用</dt><dd>{booleanValue(foregroundEvidence.applied) ? '是' : '尚无凭证'}</dd>
                <dt>提交文本匹配</dt><dd>{booleanValue(foregroundEvidence.commitTextMatched) ? '是' : '尚无凭证'}</dd>
                <dt>采集范围</dt><dd>{numberValue(foregroundEvidence.capturedContextChars)} 字</dd>
              </dl>
            </ManagementSection>
          </div>
        </DiagnosticsDisclosure>

        <ManagementSection
          title="可以尝试的修复"
          description="日常检查无需确认；只有会改变已安装输入法、服务或系统设置的操作才会先说明影响并要求确认。"
          trailing={(
            <StatusBadge
              label={runtimeRevision < 0
                ? '等待服务状态'
                : queries.capabilities.isPending ? '正在检查宿主能力'
                  : queries.capabilities.error ? '宿主能力未知'
                    : canOpenAccessibilitySettings ? '宿主可用' : '仅桌面端可用'}
              tone={runtimeRevision < 0 || queries.capabilities.isPending || queries.capabilities.error || !canOpenAccessibilitySettings ? 'warning' : 'success'}
            />
          )}
        >
          {queries.capabilities.isPending ? (
            <InlineNotice title="正在确认本机操作能力" tone="info">
              完成后会显示当前环境能够执行的修复；等待期间不会发送任何本机操作。
            </InlineNotice>
          ) : queries.capabilities.error ? null : !canOpenAccessibilitySettings ? (
            <InlineNotice title="请在已安装的应用中操作" tone="warning">
              重启服务、重新部署和打开系统设置只在已安装的应用中执行；浏览器预览保持只读。
            </InlineNotice>
          ) : runtimeRevision < 0 ? (
            <InlineNotice title="正在等待运行状态" tone="warning">
              正在同步运行状态，完成后即可继续。
            </InlineNotice>
          ) : null}
          {!queries.capabilities.isPending && !queries.capabilities.error && canOpenAccessibilitySettings && runtimeRevision >= 0 ? (
            <div className="diagnostics-action-list">
              {repairActions.map((item) => (
              <DiagnosticsRuntimeWorkflow
                action={item.action}
                description={item.description}
                key={item.action}
                nativeExternalActions={canOpenAccessibilitySettings}
                onApplied={refresh}
                risk={item.risk}
                runtimeRevision={runtimeRevision}
                title={item.title}
                transport={queries.transport}
              />
              ))}
            </div>
          ) : !queries.capabilities.isPending && !queries.capabilities.error ? <DiagnosticsActionSummary actions={repairActions} /> : null}
        </ManagementSection>

        <ManagementSection title="哪些操作需要确认">
          <DiagnosticsDisclosure className="diagnostics-boundary" summary="查看受保护操作">
            <p>清空历史、清空记忆、恢复默认、卸载，以及重新部署受管输入法都会改变本机内容或已安装组件。执行前需要单独查看影响并确认；查看状态和普通检查不需要确认。</p>
          </DiagnosticsDisclosure>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function DiagnosticsServiceList({ components }: { components: Record<string, unknown>[] }) {
  return (
    <div aria-label="本机服务状态" className="diagnostics-service-list" role="list">
      {components.map((item) => {
        const id = stringValue(item.id);
        const ok = booleanValue(item.ok);
        const title = componentLabel(id);
        const detail = componentDetail(item);
        return (
          <DiagnosticsDisclosure
            className="diagnostics-service"
            key={id}
            summary={(
              <>
                <span className="diagnostics-service__copy"><strong>{title}</strong><small>{detail}</small></span>
                <span className="diagnostics-service__meta">{serviceStatusLabel(stringValue(item.status))}</span>
                <StatusBadge label={ok ? '正常' : '需要检查'} tone={ok ? 'success' : 'warning'} />
              </>
            )}
          >
            <div className="diagnostics-service__body">
              <dl className="diagnostics-service__facts">
                <dt>当前判断</dt><dd>{ok ? '服务已报告正常' : '服务需要进一步检查'}</dd>
                <dt>检查说明</dt><dd>{detail}</dd>
                <dt>最近检查</dt><dd>{componentUpdatedAtLabel(item)}</dd>
                <dt>建议处理</dt><dd>{componentRecoveryLabel(id, ok)}</dd>
              </dl>
              <DiagnosticsDisclosure className="diagnostics-service__evidence" summary="脱敏技术记录">
                <pre>{componentEvidence(item)}</pre>
              </DiagnosticsDisclosure>
            </div>
          </DiagnosticsDisclosure>
        );
      })}
    </div>
  );
}

function DiagnosticsDisclosure({
  children,
  className,
  summary,
}: {
  children: React.ReactNode;
  className: string;
  summary: React.ReactNode;
}) {
  return (
    <Disclosure className={className} revealClassName="diagnostics-disclosure__reveal" summary={summary}>
      {children}
    </Disclosure>
  );
}

function DiagnosticsActionSummary({
  actions,
}: {
  actions: readonly { description: string; risk: 'R1' | 'R2' | 'R3'; title: string }[];
}) {
  return (
    <ul className="diagnostics-action-summary" aria-label="可用修复清单">
      {actions.map((item) => (
        <li key={item.title}>
          <div><strong>{item.title}</strong><p>{item.description}</p></div>
          {item.risk === 'R3' ? <StatusBadge label="需要确认" tone="warning" /> : null}
        </li>
      ))}
    </ul>
  );
}

function runtimeActions(aiEnabled: boolean): readonly {
  action: DiagnosticsRuntimeAction;
  description: string;
  risk: 'R1' | 'R2' | 'R3';
  title: string;
}[] {
  return [
    { action: 'register_input_source', title: '重新连接输入法', description: '刷新当前用户的输入源注册，不会清空个人词库或输入记录。', risk: 'R2' },
    { action: 'restart_sidecar', title: '重新连接本机补全服务', description: '由已安装的应用重新连接本机补全服务；当前工作不会丢失。', risk: 'R2' },
    { action: 'restart_predictor', title: '应用并重启本机模型', description: '应用已保存的设置，重新载入本机模型与补全服务，完成后自动检查状态。', risk: 'R2' },
    { action: 'redeploy_rime', title: '重新部署受管输入法', description: '把已保存的候选数量和触发延迟应用到受管输入法。这会修改已安装组件，因此需要确认。', risk: 'R3' },
    { action: 'open_accessibility_settings', title: '打开辅助功能设置', description: '打开 macOS 辅助功能权限页，不自动修改权限。', risk: 'R1' },
    aiEnabled
      ? { action: 'stop_ai', title: '暂停智能候选', description: '暂停输入后的智能候选，基础输入仍然可以使用。', risk: 'R1' }
      : { action: 'resume_ai', title: '恢复智能候选', description: '重新开启输入后的智能候选，基础输入不受影响。', risk: 'R1' },
  ];
}

function componentLabel(id: string): string {
  return ({
    inputMethod: '输入法',
    sidecar: '本机补全',
    predictor: '本机模型',
    foregroundContext: '当前应用识别',
    hybridRag: '知识检索',
    memoryCompiler: '记忆整理',
    sqlite: '本机存储',
    voiceAgent: '语音输入',
    voiceMicrophone: '麦克风权限',
    voiceAccessibility: '辅助功能权限',
    voiceRecognition: '实时转写',
    deployment: '安装状态',
    assistantCandidateDelivery: '智能候选显示',
  } as Record<string, string>)[id] ?? '其他本机组件';
}

function candidateStageItems(stages: Record<string, unknown>) {
  const definitions = [
    ['sourcePresent', '输入法功能已准备'],
    ['installedProvenance', '已安装输入法版本'],
    ['sidecarConnected', '本机补全服务已连接'],
    ['candidateProduced', '候选已生成'],
    ['foregroundRendered', '候选已显示'],
  ] as const;
  return definitions.map(([id, title]) => {
    const stage = asRecord(stages[id]);
    const ok = booleanValue(stage.ok);
    return {
      id,
      title,
      detail: ok ? '已准备好' : '等待检查或实际输入验证',
      meta: ok ? '已验证' : '待验证',
      status: <StatusBadge label={ok ? '成立' : '未成立'} tone={ok ? 'success' : 'warning'} />,
    };
  });
}

function componentDetail(item: Record<string, unknown>): string {
  const detail = stringValue(item.detail).trim();
  if (!detail) return booleanValue(item.ok) ? '运行正常' : '请打开详情继续检查';
  return publicDiagnosticDetail(detail);
}

function componentUpdatedAtLabel(item: Record<string, unknown>): string {
  const timestamp = [item.checkedAtMs, item.updatedAtMs, item.lastSeenAtMs, item.timestampMs]
    .find((value) => typeof value === 'number' && Number.isFinite(value) && value > 0);
  if (typeof timestamp !== 'number') return '随本轮刷新取得';
  return new Date(timestamp).toLocaleString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    month: 'numeric',
    second: '2-digit',
    day: 'numeric',
  });
}

function componentRecoveryLabel(id: string, ok: boolean): string {
  if (ok) return '无需处理；状态变化时刷新本页重新核对。';
  return ({
    inputMethod: '先确认当前输入法，再尝试重新连接输入法。',
    sidecar: '尝试重新连接本机补全服务，然后刷新状态。',
    predictor: '检查模型设置，必要时应用设置并重启本机模型。',
    foregroundContext: '回到真实应用输入一段文字，再刷新前台验证证据。',
    assistantCandidateDelivery: '在真实应用输入并等待智能候选显示，再刷新本页。',
    voiceRecognition: '先更新或重新部署受管输入法，再到真实应用中复测语音输入。',
    deployment: '查看“重新部署受管输入法”的影响，确认后重新部署并复测。',
    voiceMicrophone: '检查麦克风权限，然后重新尝试语音输入。',
    voiceAccessibility: '打开辅助功能设置，人工确认授权后再复测。',
  } as Record<string, string>)[id] ?? '先刷新状态；若仍异常，复制排查报告并按下方修复建议处理。';
}

function componentEvidence(item: Record<string, unknown>): string {
  const metadata = redact(asRecord(item.metadata));
  const evidence = metadata && typeof metadata === 'object' && Object.keys(metadata as Record<string, unknown>).length
    ? { evidence: metadata }
    : {};
  return JSON.stringify({
    component: componentLabel(stringValue(item.id)),
    healthy: booleanValue(item.ok),
    status: serviceStatusLabel(stringValue(item.status)),
    detail: componentDetail(item),
    checkedAt: componentUpdatedAtLabel(item),
    ...evidence,
  }, null, 2);
}

function publicDiagnosticDetail(detail: string): string {
  if (/语音代理.*版本过旧.*定稿/u.test(detail)) {
    return '已安装的语音输入组件版本较旧，暂不支持完整转写。';
  }
  if (/voice was installed from another product commit/i.test(detail)) {
    return '已安装的语音组件与当前版本不一致。';
  }
  if (/\b(?:path|sha(?:256)?|token|receipt|revision|schema)\b/i.test(detail)) {
    return '服务返回了需要进一步排查的信息，请复制报告后查看。';
  }
  return /[\u3400-\u9fff]/u.test(detail)
    ? detail
    : publicErrorText(new Error(detail), '服务需要进一步检查，请复制报告后查看。');
}

function serviceStatusLabel(value: string): string {
  if (/ready|running|healthy|ok/i.test(value)) return '运行中';
  if (/disabled|stopped|off/i.test(value)) return '未启用';
  return value ? '状态已更新' : '等待状态';
}

function inputReadinessLabel(value: string): string {
  return ({ not_selected: '尚未选为当前输入法', ready: '已准备好', unavailable: '当前不可用' } as Record<string, string>)[value] ?? '等待系统状态';
}

function predictorServiceLabel(value: string): string {
  if (/mlx|local/i.test(value)) return '本机模型';
  if (/remote|cloud/i.test(value)) return '远程模型';
  return value ? '已连接模型服务' : '等待模型服务';
}

function displayModelName(predictor: Record<string, unknown>): string {
  const model = stringValue(predictor.model).trim();
  if (!model) return '由本机配置决定';
  return model.split('/').filter(Boolean).at(-1) ?? '由本机配置决定';
}

function fingerprintLabel(value: string): string {
  const normalized = value.replace(/^sha256:/, '').trim();
  return normalized ? normalized.slice(0, 12) : '尚未报告';
}

function foregroundSourceLabel(value: string): string {
  return ({
    accessibility: '辅助功能前台文本',
    text_input_client: '输入控件文本',
  } as Record<string, string>)[value] ?? (value ? `已记录 · ${value}` : '尚无真实前台请求凭证');
}

function freshnessLabel(value: number): string {
  if (value < 0) return '尚未记录';
  if (value < 1_000) return '刚刚';
  if (value < 60_000) return `${Math.ceil(value / 1_000)} 秒前`;
  if (value < 3_600_000) return `${Math.ceil(value / 60_000)} 分钟前`;
  return `${Math.ceil(value / 3_600_000)} 小时前`;
}

function runtimeLabel(value: string): string {
  return /local|native|mlx/i.test(value) ? '本机' : value ? '已连接环境' : '等待状态';
}

function routeStateLabel(value: string): string {
  if (!value || value === 'none') return '可以使用';
  if (/not.?configured|missing|unavailable/i.test(value)) return '需要完成模型配置';
  if (/disabled|off/i.test(value)) return '当前未启用';
  return '暂不可用，请查看诊断报告';
}

function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (typeof value === 'string') {
    if (/^(?:sha256:|https?:\/\/|file:|\/)/i.test(value)) return '已隐藏';
    return value;
  }
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).flatMap(([key, item]) => {
    if (/schema(?:Version)?|pathId|operation(?:Id)?|receipt(?:Id)?|rollbackToken|payloadSha|runtimeRevision|previewToken|policy(?:Id)?|profile(?:Id|Version)?/i.test(key)) return [];
    return [[
      key,
      /token|secret|password|api.?key|authorization|cookie/i.test(key) ? (item ? 'configured' : 'not configured') : redact(item),
    ]];
  }));
}
