import { CheckCircle2, KeyRound, MessageCircle, Mic, Plus, RefreshCw, Shield, Sparkles, Waves } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, SegmentedControl, Switch, TextArea } from '@/components/primitives';
import { useVoiceQueries } from './api';
import {
  configurationMutationPathIds,
  useConfigurationMutationBoundary,
} from '@/features/configuration/api';
import {
  ManagementMutationWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  booleanValue,
  stringValue,
  valueAt,
} from '@/features/overview/management-ui';
import './voice.css';

const providers = [
  { value: 'native_streaming', label: '原生流式' },
  { value: 'realtime_websocket', label: '实时连接' },
  { value: 'http_transcription', label: 'HTTP 转写' },
] as const;

const suggestedHotwords = ['Pi', 'API Key', 'SK', 'Skill', 'GPT-5.6', '智鼬'] as const;

export function VoiceFeature() {
  const navigate = useNavigate();
  const queries = useVoiceQueries();
  const mutationBoundary = useConfigurationMutationBoundary();
  const settingsEnvelope = asRecord(queries.settings.data);
  const settings = asRecord(settingsEnvelope.settings);
  const voiceControl = asRecord(settingsEnvelope.voiceControl);
  const hotwordControl = asRecord(voiceControl.hotwords);
  const recognitionControl = asRecord(voiceControl.recognition);
  const deployedRecognition = asRecord(recognitionControl.deployed);
  const lastRecognition = asRecord(recognitionControl.lastSession);
  const runtime = asRecord(queries.runtime.data);
  const components = asRecord(runtime.components);
  const voiceSettings: Record<string, unknown> = {
    ...firstRecord(
      settings.voice,
      valueAt(settings, 'providers.voice'),
      valueAt(settingsEnvelope, 'providers.voice'),
    ),
    ...(stringValue(voiceControl.provider) ? { provider: stringValue(voiceControl.provider) } : {}),
  };
  const configuredProvider = providers.find((item) => item.value === stringValue(voiceSettings.provider))?.value ?? '';
  const [providerDraft, setProviderDraft] = useState<(typeof providers)[number]['value'] | ''>('');
  const provider = providerDraft || configuredProvider || providers[0].value;
  const credentialState = credentialStatus(
    valueAt(voiceControl, 'agent.credentialsConfigured')
      ?? voiceSettings.tokenConfigured
      ?? voiceSettings.accessTokenConfigured
      ?? valueAt(settings, 'voice.credentials.configured'),
  );
  const voiceAgent = asRecord(components.voiceAgent);
  const microphone = asRecord(components.microphone ?? components.voiceMicrophone);
  const accessibility = asRecord(components.accessibility ?? components.voiceAccessibility);
  const toolItems = arrayRecords(asRecord(queries.tools.data).items);
  const voiceTool = toolItems.find((item) => (
    stringValue(item.id) === 'ime_voice' || stringValue(item.domain) === 'voice'
  ));
  const voiceOperations = new Set(
    Array.isArray(voiceTool?.operations)
      ? voiceTool.operations.filter((item): item is string => typeof item === 'string')
      : [],
  );
  const voiceToolOnline = Boolean(
    voiceTool
    && ['online', 'available', 'ready'].includes(stringValue(voiceTool.availability).toLowerCase()),
  );
  const routeIds = new Set(queries.capabilities.data?.routeIds ?? []);
  const rawRuntimeRevision = settingsEnvelope.runtimeRevision ?? valueAt(settingsEnvelope, 'runtimeConfig.runtimeRevision');
  const runtimeRevision = typeof rawRuntimeRevision === 'number'
    && Number.isInteger(rawRuntimeRevision)
    && rawRuntimeRevision >= 0
    ? rawRuntimeRevision
    : null;
  const savedHotwords = useMemo(
    () => stringArray(voiceSettings.hotwords),
    [voiceSettings.hotwords],
  );
  const savedHotwordSignature = JSON.stringify({
    enabled: booleanValue(voiceSettings.hotwordsEnabled),
    words: savedHotwords,
  });
  const [hotwordsEnabled, setHotwordsEnabled] = useState(false);
  const [hotwordsText, setHotwordsText] = useState('');
  useEffect(() => {
    setHotwordsEnabled(booleanValue(voiceSettings.hotwordsEnabled));
    setHotwordsText(savedHotwords.join('\n'));
  }, [savedHotwordSignature]);
  const hotwordDraft = useMemo(
    () => normalizeHotwordDraft(hotwordsText, hotwordsEnabled),
    [hotwordsEnabled, hotwordsText],
  );
  const hotwordDirty = hotwordsEnabled !== booleanValue(voiceSettings.hotwordsEnabled)
    || JSON.stringify(hotwordDraft.words) !== JSON.stringify(savedHotwords);
  const toolChecking = routeIds.has('agent.tools.list') && queries.tools.isPending;
  const providerHandoffAvailable = voiceToolOnline
    && routeIds.has('agent.session.prompt')
    && ['provider_status', 'provider_preview', 'provider_apply', 'provider_rollback'].every((operation) => voiceOperations.has(operation));
  const privacyHandoffAvailable = voiceToolOnline
    && routeIds.has('agent.session.prompt')
    && voiceOperations.has('privacy_policy');
  const error = queries.capabilities.error as Error | null;
  const pending = queries.capabilities.isPending;
  const refreshing = queries.settings.isFetching
    || queries.schema.isFetching
    || queries.runtime.isFetching
    || queries.tools.isFetching;
  const refresh = () => void Promise.all([
    queries.capabilities.refetch(),
    queries.settings.refetch(),
    queries.schema.refetch(),
    queries.runtime.refetch(),
    ...(queries.tools.isEnabled ? [queries.tools.refetch()] : []),
  ]);

  const handoff = (kind: 'provider' | 'privacy') => {
    const selected = providers.find((item) => item.value === provider)?.label ?? '所选语音服务';
    const draft = kind === 'privacy'
      ? '请告诉我当前语音输入会保存哪些内容、哪些内容不会保存，以及发送前需要我确认什么。只依据当前真实配置回答。'
      : `把语音服务切换为“${selected}”。请先展示会发生的变化并等待我确认，确认前不要修改设置。`;
    navigate({ pathname: '/agent', search: `?${new URLSearchParams({ draft })}` });
  };

  const addSuggestedHotword = (word: string) => {
    const current = normalizeHotwordDraft(hotwordsText, false);
    if (current.error) return;
    const suggestionKey = hotwordDedupeKey(word);
    if (current.words.some((item) => hotwordDedupeKey(item) === suggestionKey)) return;
    setHotwordsText([...current.words, word].join('\n'));
  };

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={refreshing} onClick={refresh} size="small">刷新</Button>}
      description="查看语音输入是否就绪，并在确认后切换语音服务。"
      eyebrow="VOICE"
      routeId="voice"
      title="语音输入"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="准备情况">
          <MetricStrip items={[
            { label: '语音能力', value: toolChecking ? '正在检查' : providerHandoffAvailable ? '可用' : '暂不可用', detail: providerHandoffAvailable ? '可查看状态并切换服务' : '不会执行配置变更', icon: Waves, tone: providerHandoffAvailable ? 'success' : toolChecking ? 'neutral' : 'warning' },
            { label: '麦克风', value: queries.runtime.isPending ? '正在检查' : permissionLabel(microphone), detail: '需要系统授权', icon: Mic, tone: booleanValue(microphone.ok) ? 'success' : queries.runtime.isPending ? 'neutral' : 'warning' },
            { label: '辅助功能', value: queries.runtime.isPending ? '正在检查' : permissionLabel(accessibility), detail: '用于将文字写回当前应用', icon: Shield, tone: booleanValue(accessibility.ok) ? 'success' : queries.runtime.isPending ? 'neutral' : 'warning' },
            { label: '访问凭据', value: credentialState.label, detail: '保存内容不会在页面显示', icon: KeyRound, tone: credentialState.tone },
          ]} />
          <InlineNotice title="隐私保护" tone="info">页面不会显示已保存的密钥或请求头。没有取得明确状态时，相关操作保持关闭。</InlineNotice>
          {queries.runtime.error ? <InlineNotice title="权限状态读取失败" tone="warning">暂时无法确认麦克风和辅助功能权限，请刷新后重试。</InlineNotice> : null}
        </ManagementSection>

        <ManagementSection
          title="语音服务"
          description="选择想使用的服务；真正切换前会在对话中再次确认。"
          trailing={<StatusBadge label={currentProviderStatus(queries.settings.isPending, Boolean(queries.settings.error), configuredProvider)} tone={configuredProvider ? 'info' : 'warning'} />}
        >
          <div className="voice-service-layout">
            <div className="voice-service-choice">
              <strong>希望使用的服务</strong>
              <SegmentedControl aria-label="希望使用的语音服务" items={providers} onValueChange={setProviderDraft} value={provider} />
              <Button
                disabled={!providerHandoffAvailable}
                leadingIcon={<MessageCircle size={15} />}
                onClick={() => handoff('provider')}
                size="small"
                variant="primary"
              >
                {toolChecking ? '正在检查' : providerHandoffAvailable ? '让智鼬确认切换' : '当前不可切换'}
              </Button>
            </div>
            {toolChecking ? (
              <InlineNotice title="正在确认可用能力" tone="info">检查完成前不会发送请求，也不会写入任何设置。</InlineNotice>
            ) : providerHandoffAvailable ? (
              <InlineNotice title="确认后才会切换" tone="success">点击后会打开对话，并把请求保留为待发送草稿。发送后仍需确认影响，页面不会直接改写设置。</InlineNotice>
            ) : (
              <InlineNotice title="语音管理暂不可用" tone="warning">当前没有可验证的语音管理能力。选择服务只会停留在本页，不会写入任何设置。</InlineNotice>
            )}
          </div>
          {queries.settings.error ? <InlineNotice title="当前设置读取失败" tone="warning">暂时无法核对正在使用的语音服务，请刷新后重试。</InlineNotice> : null}
          {queries.tools.error ? <InlineNotice title="状态读取失败" tone="warning">暂时无法确认语音管理能力，请刷新后重试。</InlineNotice> : null}
        </ManagementSection>

        <ManagementSection title="按住说话与热词" description="热词只在你预览并确认保存后发送给当前语音识别服务。">
          <div className="mgmt-grid-2">
            <OperationalList items={[
              { id: 'push-to-talk', title: '按住说话', detail: '按下开始、松开后形成最终文字', meta: hotkeyLabel(stringValue(valueAt(voiceControl, 'agent.hotkeyMode'), stringValue(voiceSettings.hotkey))), status: <StatusBadge label={booleanValue(voiceAgent.ok) ? '已就绪' : '待检查'} tone={booleanValue(voiceAgent.ok) ? 'success' : 'warning'} /> },
              { id: 'hotwords', title: '当前词表', detail: '控制中心与语音输入使用同一份本地词表', meta: `${savedHotwords.length} 条`, status: <StatusBadge label={hotwordApplyLabel(hotwordControl)} tone={hotwordApplyTone(hotwordControl)} /> },
            ]} />
            <div className="mgmt-stack">
              <Switch
                checked={hotwordsEnabled}
                description="关闭时保留词表，但不会随识别请求发送。"
                label="启用热词"
                onCheckedChange={setHotwordsEnabled}
              />
              <label className="voice-hotword-editor">
                <span>每行一个词</span>
                <TextArea
                  aria-label="语音热词"
                  onChange={(event) => setHotwordsText(event.target.value)}
                  placeholder="例如：智鼬"
                  rows={7}
                  value={hotwordsText}
                />
                <small>{hotwordDraft.words.length} / 32 条，每个 2 至 9 个字符</small>
              </label>
              {hotwordDraft.error ? <InlineNotice title="词表需要调整" tone="warning">{hotwordDraft.error}</InlineNotice> : null}
              <div className="voice-hotword-suggestions" aria-label="热词建议">
                {suggestedHotwords.map((word) => (
                  <button key={word} onClick={() => addSuggestedHotword(word)} type="button">
                    <Plus size={12} aria-hidden="true" />
                    {word}
                  </button>
                ))}
              </div>
              <ManagementMutationWorkflow
                availability={mutationBoundary.availability(
                  runtimeRevision === null
                    ? '当前语音设置尚未同步，刷新后才能预览。'
                    : hotwordDraft.error
                      ? '请先修正上方词表。'
                      : !hotwordDirty
                        ? '修改词表或启用状态后才能生成预览。'
                        : '',
                )}
                description="保存为语音输入实际使用的本地词表；下一次听写开始前会重新载入。"
                draftKey={JSON.stringify({ enabled: hotwordsEnabled, words: hotwordDraft.words, runtimeRevision })}
                mutationKey={['voice', 'mutation', 'hotwords']}
                onApply={async (preview) => parseManagementWorkReceipt(
                  await mutationBoundary.request({
                    pathId: configurationMutationPathIds.apply,
                    body: {
                      changes: preview.context.changes,
                      expectedRuntimeRevision: preview.expectedRuntimeRevision,
                      previewToken: preview.previewToken,
                      payloadSha256: preview.payloadSha256,
                      confirmText: preview.requiredConfirm,
                    },
                  }),
                  configurationMutationPathIds.apply,
                  preview.payloadSha256,
                )}
                onApplied={() => void Promise.all([queries.settings.refetch(), queries.runtime.refetch()])}
                onPreview={async () => {
                  if (runtimeRevision === null || hotwordDraft.error || !hotwordDirty) {
                    throw new Error('热词草案或当前设置状态已失效，请刷新后重试。');
                  }
                  const context = {
                    changes: {
                      'voice.hotwordsEnabled': hotwordsEnabled,
                      'voice.hotwords': hotwordDraft.words,
                    },
                  };
                  return parseManagementWorkPreview(
                    await mutationBoundary.request({
                      pathId: configurationMutationPathIds.preview,
                      body: { ...context, expectedRuntimeRevision: runtimeRevision },
                    }),
                    configurationMutationPathIds.apply,
                    context,
                  );
                }}
                onRollback={async (receipt, preview) => parseManagementWorkReceipt(
                  await mutationBoundary.request({
                    pathId: configurationMutationPathIds.rollback,
                    body: {
                      receiptId: receipt.receiptId,
                      rollbackToken: receipt.rollbackToken,
                      payloadSha256: receipt.payloadSha256,
                      confirmText: 'rollback',
                    },
                  }),
                  configurationMutationPathIds.rollback,
                  preview.payloadSha256,
                )}
                onRolledBack={() => void Promise.all([queries.settings.refetch(), queries.runtime.refetch()])}
                risk="R1"
                title="保存热词词表"
              />
              <Button
                disabled={!privacyHandoffAvailable}
                leadingIcon={<MessageCircle size={15} />}
                onClick={() => handoff('privacy')}
                size="small"
              >
                {toolChecking ? '正在检查' : privacyHandoffAvailable ? '查看语音处理说明' : '处理说明暂不可用'}
              </Button>
            </div>
          </div>
        </ManagementSection>

        <ManagementSection title="定稿质量" description="检查语音输入能否把临时识别结果顺滑地整理成最终文本。">
          <MetricStrip items={[
            { label: '最终二次识别', value: deployedLabel(deployedRecognition.secondPass), detail: '停顿后重新识别完整语句', icon: CheckCircle2, tone: deployedTone(deployedRecognition.secondPass) },
            { label: '语义顺滑', value: deployedLabel(deployedRecognition.semanticSmoothing), detail: '整理口头语、重复与赘余', icon: Sparkles, tone: deployedTone(deployedRecognition.semanticSmoothing) },
            { label: '完整结果替换', value: deployedLabel(deployedRecognition.fullResultReplacement), detail: '最终稿替换临时稿，不继续追加', icon: Waves, tone: deployedTone(deployedRecognition.fullResultReplacement) },
            { label: '最近一次定稿', value: booleanValue(lastRecognition.finalReceived) ? '已收到' : '暂无验证', detail: finalLatencyLabel(lastRecognition.finalLatencyMs), icon: Mic, tone: booleanValue(lastRecognition.finalReceived) ? 'success' : 'warning' },
          ]} />
          {deployedRecognition.binaryFound === false ? <InlineNotice title="语音输入尚未就绪" tone="warning">更新并重新打开应用后刷新，即可检查二次识别与语义顺滑是否可用。</InlineNotice> : null}
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function firstRecord(...values: unknown[]): Record<string, unknown> {
  for (const value of values) {
    const record = asRecord(value);
    if (Object.keys(record).length > 0) return record;
  }
  return {};
}

function providerLabel(value: string): string {
  return providers.find((item) => item.value === value)?.label ?? '未知服务';
}

function currentProviderStatus(pending: boolean, failed: boolean, value: string): string {
  if (pending) return '正在读取当前设置';
  if (failed) return '当前设置读取失败';
  if (value) return `当前：${providerLabel(value)}`;
  return '当前设置未提供';
}

function permissionLabel(value: Record<string, unknown>): string {
  if (value.ok === true) return '已允许';
  if (value.ok === false || Object.keys(value).length > 0) return '未允许';
  return '未检查';
}

function hotkeyLabel(value: string): string {
  const normalized = value.trim().toLocaleLowerCase('en-US').replace(/[ -]+/g, '_');
  if (normalized === 'event_tap') return '按住鼠标中键';
  if (normalized === 'passive_middle_mouse' || normalized === 'middle_mouse') return '鼠标中键';
  if (normalized === 'option_+_space' || normalized === 'option_space') return 'Option + 空格';
  return value && /[\u3400-\u9fff]/u.test(value) ? value : '未读取到快捷键';
}

function credentialStatus(value: unknown): { label: string; tone: 'success' | 'warning' } {
  if (value === true) return { label: '已配置', tone: 'success' };
  if (value === false) return { label: '未配置', tone: 'warning' };
  return { label: '未读取到状态', tone: 'warning' };
}

type VoiceStatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

function normalizeHotwordDraft(text: string, enabled: boolean): { words: string[]; error: string } {
  const words: string[] = [];
  const seen = new Set<string>();
  for (const rawWord of text.split(/\r?\n/u)) {
    const word = rawWord.trim().replace(/\s+/gu, ' ');
    if (!word) continue;
    const length = Array.from(word).length;
    if (length < 2 || length > 9) {
      return { words, error: `“${word}”需要保持在 2 至 9 个字符。` };
    }
    if (!Array.from(word).every((character) => /[\p{L}\p{N}\s.\-_+#/&]/u.test(character))) {
      return { words, error: `“${word}”包含当前语音服务不支持的符号。` };
    }
    const key = hotwordDedupeKey(word);
    if (seen.has(key)) continue;
    seen.add(key);
    words.push(word);
    if (words.length > 32) {
      return { words, error: '热词最多保存 32 条。' };
    }
  }
  if (enabled && words.length === 0) {
    return { words, error: '启用热词前，请至少添加一条热词。' };
  }
  return { words, error: '' };
}

function hotwordDedupeKey(value: string): string {
  return value.normalize('NFKC').toLocaleLowerCase();
}

function hotwordApplyLabel(value: Record<string, unknown>): string {
  if (value.ok === false || stringValue(value.applyState) === 'invalid') return '配置异常';
  if (stringValue(value.applyState) === 'loaded') return '已载入';
  if (stringValue(value.applyState) === 'next_session') return '下次听写生效';
  if (value.inSync === true) return '已同步';
  return '待检查';
}

function hotwordApplyTone(value: Record<string, unknown>): VoiceStatusTone {
  if (value.ok === false || stringValue(value.applyState) === 'invalid') return 'danger';
  if (stringValue(value.applyState) === 'loaded' || value.inSync === true) return 'success';
  if (stringValue(value.applyState) === 'next_session') return 'info';
  return 'warning';
}

function deployedLabel(value: unknown): string {
  if (value === true) return '当前可用';
  if (value === false) return '当前不可用';
  return '未检查';
}

function deployedTone(value: unknown): VoiceStatusTone {
  if (value === true) return 'success';
  if (value === false) return 'warning';
  return 'neutral';
}

function finalLatencyLabel(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return '尚无实际听写数据';
  }
  return `定稿用时 ${Math.round(value)} 毫秒`;
}
