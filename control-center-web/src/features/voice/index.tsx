import { CheckCircle2, KeyRound, Mic, Play, Plus, RefreshCw, Save, Shield, Sparkles, Square, Waves } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Button, Disclosure, Field, Input, SegmentedControl, Select, Switch, TextArea } from '@/components/primitives';
import { useVoiceCredentialStatus, useVoiceQueries } from './api';
import {
  parsePiModelCatalogOptions,
  supportedPiThinkingLevels,
} from '@/features/agent/model-catalog-options';
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
  asRecord,
  booleanValue,
  publicErrorText,
  stringValue,
  valueAt,
} from '@/features/overview/management-ui';
import type {
  VoiceCredentialSaveRequest,
  VoiceNativeActionId,
  VoiceNativeActionReceipt,
  VoiceProviderId,
} from '@/platform/transport';
import { useProductIdentity } from '@/features/identity/product-identity';
import './voice.css';

const providers = [
  {
    value: 'native_streaming',
    label: '实时听写',
    description: '边说边显示，说完后补充完整文字，也支持本次热词。',
    supportsHotwords: true,
  },
  {
    value: 'realtime_websocket',
    label: '实时服务',
    description: '边说边显示；可在高级连接设置中使用自定义服务。',
    supportsHotwords: false,
  },
  {
    value: 'http_transcription',
    label: '上传后转写',
    description: '松开按键后再转写整段音频；可在高级连接设置中使用自定义服务。',
    supportsHotwords: false,
  },
] as const;

const hotkeys = [
  { value: 'middle_mouse', label: '鼠标中键' },
  { value: 'right_option', label: '右 Option' },
  { value: 'option_space', label: 'Option + 空格' },
] as const;

const defaultSuggestedHotwords = [
  'PAW', '个人计划', '常用联系人', '项目名称', '专业名词', '英文缩写',
  '补全模型', 'GPT-5.6', 'Luna', 'Terra',
] as const;

export function VoiceFeature() {
  const identity = useProductIdentity();
  const queries = useVoiceQueries();
  const mutationBoundary = useConfigurationMutationBoundary();
  const settingsEnvelope = asRecord(queries.settings.data);
  const settings = asRecord(settingsEnvelope.settings);
  const voiceControl = asRecord(settingsEnvelope.voiceControl);
  const hotwordControl = asRecord(voiceControl.hotwords);
  const recognitionControl = asRecord(voiceControl.recognition);
  const deployedRecognition = asRecord(recognitionControl.deployed);
  const deployedRecognitionState = stringValue(deployedRecognition.state, 'unchecked');
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
  const configuredHotkey = hotkeys.find((item) => item.value === stringValue(voiceSettings.hotkey))?.value
    ?? hotkeys.find((item) => item.value === stringValue(voiceControl.hotkey))?.value
    ?? 'middle_mouse';
  const modelCatalog = useMemo(
    () => parsePiModelCatalogOptions(queries.modelCatalog.data),
    [queries.modelCatalog.data],
  );
  const configuredRefinementModel = stringValue(voiceSettings.refinementModel, 'inherit');
  const configuredRefinementThinking = stringValue(
    voiceSettings.refinementThinkingLevel,
    'off',
  );
  const [provider, setProvider] = useState<VoiceProviderId>(configuredProvider || 'native_streaming');
  const [hotkey, setHotkey] = useState<(typeof hotkeys)[number]['value']>(configuredHotkey);
  const [refinementModel, setRefinementModel] = useState(configuredRefinementModel);
  const [refinementThinking, setRefinementThinking] = useState(configuredRefinementThinking);
  useEffect(() => setProvider(configuredProvider || 'native_streaming'), [configuredProvider]);
  useEffect(() => setHotkey(configuredHotkey), [configuredHotkey]);
  useEffect(() => setRefinementModel(configuredRefinementModel), [configuredRefinementModel]);
  useEffect(() => setRefinementThinking(configuredRefinementThinking), [configuredRefinementThinking]);
  const credentials = useVoiceCredentialStatus(provider);
  const credentialState = credentialStatus(credentials.status.data?.configured);
  const voiceAgent = asRecord(components.voiceAgent);
  const microphone = asRecord(components.microphone ?? components.voiceMicrophone);
  const accessibility = asRecord(components.accessibility ?? components.voiceAccessibility);
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
  const selectedHotwordKeys = new Set(hotwordDraft.words.map(hotwordDedupeKey));
  const suggestedHotwords = [...new Set([...defaultSuggestedHotwords, identity.assistantName])]
    .filter((word) => !selectedHotwordKeys.has(hotwordDedupeKey(word)));
  const hotwordDirty = hotwordsEnabled !== booleanValue(voiceSettings.hotwordsEnabled)
    || JSON.stringify(hotwordDraft.words) !== JSON.stringify(savedHotwords);
  const serviceDirty = provider !== (configuredProvider || 'native_streaming') || hotkey !== configuredHotkey;
  const selectedProvider = providers.find((item) => item.value === provider) ?? providers[0];
  const activeProvider = providers.find(
    (item) => item.value === (configuredProvider || 'native_streaming'),
  ) ?? providers[0];
  const hotwordsSupported = activeProvider.supportsHotwords;
  const refinementDirty = refinementModel !== configuredRefinementModel
    || refinementThinking !== configuredRefinementThinking;
  const resolvedRefinementReference = refinementModel === 'inherit'
    ? modelCatalog.selectedReference
    : refinementModel;
  const selectedRefinementModel = modelCatalog.models.find(
    (model) => model.reference === resolvedRefinementReference,
  );
  const refinementThinkingLevels = supportedPiThinkingLevels(
    selectedRefinementModel,
    { includeOff: true },
  );
  const nativeActionsAvailable = queries.capabilities.data?.native.tcc === true
    && typeof queries.transport.runVoiceAction === 'function';
  const agentRunning = booleanValue(voiceAgent.ok) || booleanValue(valueAt(voiceControl, 'agent.running'));
  const runtimeStatusUnavailable = Boolean(queries.runtime.error);
  const error = queries.capabilities.error as Error | null;
  const pending = queries.capabilities.isPending
    || (queries.modelCatalogSupported && queries.modelCatalog.isPending);
  const refreshing = queries.settings.isFetching
    || queries.schema.isFetching
    || queries.runtime.isFetching
    || (queries.modelCatalogSupported && queries.modelCatalog.isFetching)
    || credentials.status.isFetching;
  const refresh = () => void Promise.all([
    queries.capabilities.refetch(),
    queries.settings.refetch(),
    queries.schema.refetch(),
    queries.runtime.refetch(),
    ...(queries.modelCatalogSupported ? [queries.modelCatalog.refetch()] : []),
    ...(credentials.status.isEnabled ? [credentials.status.refetch()] : []),
  ]);

  const changeRefinementModel = (value: string) => {
    setRefinementModel(value);
    const reference = value === 'inherit' ? modelCatalog.selectedReference : value;
    const selected = modelCatalog.models.find((model) => model.reference === reference);
    const levels = supportedPiThinkingLevels(selected, { includeOff: true });
    if (!levels.includes(refinementThinking)) {
      setRefinementThinking(levels.includes('off') ? 'off' : levels[0] ?? 'off');
    }
  };

  const [nativeReceipt, setNativeReceipt] = useState<VoiceNativeActionReceipt | null>(null);
  const voiceAction = useMutation({
    mutationKey: ['voice', 'native-action'],
    mutationFn: async (action: VoiceNativeActionId) => {
      if (!queries.transport.runVoiceAction) throw new Error('当前控制中心不支持本机语音操作。');
      return queries.transport.runVoiceAction(action);
    },
    onSuccess: (receipt) => {
      setNativeReceipt(receipt);
      void Promise.all([queries.runtime.refetch(), queries.settings.refetch()]);
    },
  });

  const [credentialDraft, setCredentialDraft] = useState(() => defaultCredentialDraft(provider));
  useEffect(() => setCredentialDraft(defaultCredentialDraft(provider)), [provider]);
  const credentialSave = useMutation({
    mutationKey: ['voice', 'credentials', provider],
    mutationFn: async () => {
      if (!queries.transport.saveVoiceCredentials) throw new Error('当前控制中心没有可用的 Keychain 桥接。');
      const request = validateCredentialDraft(provider, credentialDraft);
      return queries.transport.saveVoiceCredentials(request);
    },
    onSuccess: () => {
      setCredentialDraft((current) => ({ ...current, accessToken: '' }));
      void credentials.status.refetch();
      if (queries.transport.runVoiceAction) void queries.transport.runVoiceAction('reload_configuration');
    },
  });

  const addSuggestedHotword = (word: string) => {
    const current = normalizeHotwordDraft(hotwordsText, false);
    if (current.error) return;
    const suggestionKey = hotwordDedupeKey(word);
    if (current.words.some((item) => hotwordDedupeKey(item) === suggestionKey)) return;
    setHotwordsText([...current.words, word].join('\n'));
  };

  const reloadVoice = () => {
    void Promise.all([queries.settings.refetch(), queries.runtime.refetch()]);
    if (queries.transport.runVoiceAction) {
      void queries.transport.runVoiceAction('reload_configuration').then(setNativeReceipt).catch(() => undefined);
    }
  };

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={refreshing} onClick={refresh} size="small">刷新</Button>}
      description="把说话变成输入文字。这里只负责听写，不会让伙伴朗读，也不会额外保存语音。"
      eyebrow={`说给${identity.assistantName}听`}
      routeId="voice"
      title="语音输入"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="准备情况">
          <MetricStrip items={[
            { label: '听写服务', value: queries.runtime.isPending ? '正在检查' : runtimeStatusUnavailable ? '状态未知' : agentRunning ? '运行中' : '未运行', detail: runtimeStatusUnavailable ? '暂时无法读取本机听写服务状态' : stringValue(valueAt(voiceControl, 'agent.statusText')) || '随时按住快捷键开始听写', icon: Waves, tone: agentRunning && !runtimeStatusUnavailable ? 'success' : queries.runtime.isPending ? 'neutral' : 'warning' },
            { label: '麦克风', value: queries.runtime.isPending ? '正在检查' : runtimeStatusUnavailable ? '状态未知' : permissionLabel(microphone), detail: runtimeStatusUnavailable ? '暂时无法读取系统授权' : '需要系统授权', icon: Mic, tone: booleanValue(microphone.ok) && !runtimeStatusUnavailable ? 'success' : queries.runtime.isPending ? 'neutral' : 'warning' },
            { label: '辅助功能', value: queries.runtime.isPending ? '正在检查' : runtimeStatusUnavailable ? '状态未知' : permissionLabel(accessibility), detail: runtimeStatusUnavailable ? '暂时无法读取系统授权' : '用于将文字写回当前应用', icon: Shield, tone: booleanValue(accessibility.ok) && !runtimeStatusUnavailable ? 'success' : queries.runtime.isPending ? 'neutral' : 'warning' },
            { label: '连接信息', value: credentialState.label, detail: '按转写服务分别保存在钥匙串', icon: KeyRound, tone: credentialState.tone },
          ]} />
          <InlineNotice title="隐私保护" tone="info">页面不会显示已保存的密钥或请求头。没有取得明确状态时，相关操作保持关闭。</InlineNotice>
          {queries.runtime.error ? (
            <div className="voice-runtime-issue">
              <InlineNotice title="听写状态读取失败" tone="warning">暂时无法确认听写服务、麦克风和辅助功能状态；已保存设置不会改变。</InlineNotice>
              <Button loading={queries.runtime.isFetching} onClick={() => void queries.runtime.refetch()} size="small">重试听写状态</Button>
            </div>
          ) : null}
        </ManagementSection>

        <ManagementSection title="启用听写" description="启动听写服务，并允许它使用麦克风、把文字送回你正在输入的应用。">
          <div className="voice-native-actions">
            <div aria-labelledby="voice-agent-actions-label" className="voice-native-action-group" role="group">
              <span id="voice-agent-actions-label">听写服务</span>
              <Button
                aria-label={agentRunning ? '停止听写服务' : '启动听写服务'}
                aria-describedby={!nativeActionsAvailable ? 'voice-native-actions-availability' : undefined}
                disabled={!nativeActionsAvailable}
                leadingIcon={agentRunning ? <Square size={14} /> : <Play size={14} />}
                loading={voiceAction.isPending && ['start_agent', 'stop_agent'].includes(voiceAction.variables ?? '')}
                onClick={() => voiceAction.mutate(agentRunning ? 'stop_agent' : 'start_agent')}
                size="small"
                variant="primary"
              >
                {agentRunning ? '停止听写' : '启动听写'}
              </Button>
            </div>
            <div aria-labelledby="voice-microphone-actions-label" className="voice-native-action-group" role="group">
              <span id="voice-microphone-actions-label">麦克风</span>
              <Button aria-describedby={!nativeActionsAvailable ? 'voice-native-actions-availability' : undefined} disabled={!nativeActionsAvailable || !agentRunning} leadingIcon={<Mic size={14} />} loading={voiceAction.isPending && voiceAction.variables === 'request_microphone_permission'} onClick={() => voiceAction.mutate('request_microphone_permission')} size="small">请求权限</Button>
              <Button aria-describedby={!nativeActionsAvailable ? 'voice-native-actions-availability' : undefined} disabled={!nativeActionsAvailable} loading={voiceAction.isPending && voiceAction.variables === 'open_microphone_settings'} onClick={() => voiceAction.mutate('open_microphone_settings')} size="small" variant="quiet">打开设置</Button>
            </div>
            <div aria-labelledby="voice-accessibility-actions-label" className="voice-native-action-group" role="group">
              <span id="voice-accessibility-actions-label">辅助功能</span>
              <Button aria-describedby={!nativeActionsAvailable ? 'voice-native-actions-availability' : undefined} disabled={!nativeActionsAvailable || !agentRunning} leadingIcon={<Shield size={14} />} loading={voiceAction.isPending && voiceAction.variables === 'request_accessibility_permission'} onClick={() => voiceAction.mutate('request_accessibility_permission')} size="small">请求权限</Button>
              <Button aria-describedby={!nativeActionsAvailable ? 'voice-native-actions-availability' : undefined} disabled={!nativeActionsAvailable} loading={voiceAction.isPending && voiceAction.variables === 'open_accessibility_settings'} onClick={() => voiceAction.mutate('open_accessibility_settings')} size="small" variant="quiet">打开设置</Button>
            </div>
          </div>
          {!nativeActionsAvailable ? <div id="voice-native-actions-availability"><InlineNotice title="请在已安装的应用中操作" tone="warning">网页端不能启动听写或打开系统授权；请回到已安装的{identity.productName}。</InlineNotice></div> : null}
          {voiceAction.error ? <InlineNotice title="语音操作失败" tone="danger">{publicErrorText(voiceAction.error, '本机语音操作没有完成。')}</InlineNotice> : null}
          {nativeReceipt && !nativeReceipt.accepted ? <InlineNotice title="这次操作没有完成" tone="danger">{publicErrorText(nativeReceipt.error, '系统没有接受这次操作。')}</InlineNotice> : null}
          {nativeReceipt?.accepted ? <InlineNotice title="听写状态已更新" tone="success">{nativeReceipt.status.statusText}</InlineNotice> : null}
        </ManagementSection>

        <ManagementSection
          title="转写引擎与按键"
          description="选择转写服务和按住说话的快捷键；保存后，下一次听写会使用新设置。"
          trailing={<StatusBadge label={currentProviderStatus(queries.settings.isPending, Boolean(queries.settings.error), configuredProvider)} tone={configuredProvider ? 'info' : 'warning'} />}
        >
          <div className="voice-service-layout">
            <div className="voice-service-choice">
              <strong>转写引擎</strong>
              <SegmentedControl aria-label="语音转写引擎" items={providers} onValueChange={setProvider} value={provider} />
              <p className="mgmt-muted">{selectedProvider.description}</p>
              <strong>按住说话</strong>
              <SegmentedControl aria-label="语音快捷键" items={hotkeys} onValueChange={setHotkey} value={hotkey} />
            </div>
            <ManagementMutationWorkflow
              availability={mutationBoundary.availability(
                runtimeRevision === null
                  ? '当前语音设置尚未同步，刷新后才能继续保存。'
                  : !serviceDirty
                    ? '选择不同的服务或快捷键后才能保存。'
                    : '',
              )}
              description="只更新转写引擎和快捷键；保存后，听写服务会自动重新载入。"
              draftKey={JSON.stringify({ provider, hotkey, runtimeRevision })}
              mutationKey={['voice', 'mutation', 'service']}
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
              onApplied={reloadVoice}
              onPreview={async () => {
                if (runtimeRevision === null || !serviceDirty) throw new Error('语音设置草案没有可应用的变化。');
                const context = { changes: { 'voice.provider': provider, 'voice.hotkey': hotkey } };
                return parseManagementWorkPreview(
                  await mutationBoundary.request({ pathId: configurationMutationPathIds.preview, body: { ...context, expectedRuntimeRevision: runtimeRevision } }),
                  configurationMutationPathIds.apply,
                  context,
                );
              }}
              onRollback={async (receipt, preview) => parseManagementWorkReceipt(
                await mutationBoundary.request({
                  pathId: configurationMutationPathIds.rollback,
                  body: { receiptId: receipt.receiptId, rollbackToken: receipt.rollbackToken, payloadSha256: receipt.payloadSha256, confirmText: 'rollback' },
                }),
                configurationMutationPathIds.rollback,
                preview.payloadSha256,
              )}
              onRolledBack={reloadVoice}
              risk="R1"
              title="保存转写引擎与按键"
            />
          </div>
          {queries.settings.error ? <InlineNotice title="当前设置读取失败" tone="warning">暂时无法核对正在使用的转写引擎，请刷新后重试。</InlineNotice> : null}
        </ManagementSection>

        <ManagementSection title="连接信息" description="连接当前转写服务所需的信息只保存在 macOS 钥匙串中；保存后不会再次显示原值。">
          <Disclosure className="voice-connection-details" summary="配置服务连接">
            <div className="voice-connection-details__content">
          <div className="voice-credential-grid">
            <Field description={credentialState.label === '已配置' ? '已配置；留空可保留现有连接信息。' : '首次保存必须填写。'} htmlFor="voice-access-token" label="访问令牌">
              <Input autoComplete="new-password" id="voice-access-token" onChange={(event) => setCredentialDraft((current) => ({ ...current, accessToken: event.target.value }))} placeholder={credentialState.label === '已配置' ? '已配置，留空保持不变' : '输入访问令牌'} type="password" value={credentialDraft.accessToken} />
            </Field>
            {provider === 'native_streaming' ? (
              <>
                <Field htmlFor="voice-app-id" label="应用编号"><Input id="voice-app-id" onChange={(event) => setCredentialDraft((current) => ({ ...current, appId: event.target.value }))} value={credentialDraft.appId} /></Field>
                <Field htmlFor="voice-resource-id" label="资源编号"><Input id="voice-resource-id" onChange={(event) => setCredentialDraft((current) => ({ ...current, resourceId: event.target.value }))} value={credentialDraft.resourceId} /></Field>
              </>
            ) : (
              <>
                <Field htmlFor="voice-endpoint" label={provider === 'realtime_websocket' ? '实时连接地址' : '转写服务地址'}><Input id="voice-endpoint" onChange={(event) => setCredentialDraft((current) => ({ ...current, endpoint: event.target.value }))} value={credentialDraft.endpoint} /></Field>
                <Field htmlFor="voice-model" label="转写模型"><Input id="voice-model" onChange={(event) => setCredentialDraft((current) => ({ ...current, model: event.target.value }))} value={credentialDraft.model} /></Field>
                <Field description="按服务说明填写；保存后不会重新显示。" htmlFor="voice-headers" label="附加连接信息（JSON）"><TextArea id="voice-headers" onChange={(event) => setCredentialDraft((current) => ({ ...current, headersJson: event.target.value }))} placeholder='{"X-Project":"..."}' rows={4} value={credentialDraft.headersJson} /></Field>
              </>
            )}
          </div>
          {serviceDirty ? <InlineNotice title="先保存引擎选择" tone="warning">连接信息按引擎分别保存。请先完成上方引擎切换，再保存当前引擎的连接信息。</InlineNotice> : null}
          {!credentials.supported ? <InlineNotice title="安全存储暂不可用" tone="warning">当前页面不能访问 macOS 钥匙串，因此不会发送或保存这些信息。</InlineNotice> : null}
          {credentials.status.error ? <InlineNotice title="账号状态读取失败" tone="danger">暂时无法确认钥匙串中是否已经保存账号信息，请刷新后重试。</InlineNotice> : null}
          {credentialSave.error ? <InlineNotice title="账号保存失败" tone="danger">{publicErrorText(credentialSave.error, '账号信息没有保存完成。')}</InlineNotice> : null}
          {credentialSave.isSuccess ? <InlineNotice title="账号已安全保存" tone="success">访问令牌已经写入 macOS 钥匙串，页面没有读取或显示保存值。</InlineNotice> : null}
          <div className="voice-credential-actions">
            <Button disabled={!credentials.supported || serviceDirty} leadingIcon={<Save size={15} />} loading={credentialSave.isPending} onClick={() => credentialSave.mutate()} variant="primary">安全保存账号</Button>
          </div>
            </div>
          </Disclosure>
        </ManagementSection>

        <ManagementSection title="按住说话与专有词" description="在这里设置按住说话和常用专有词。词表会留在本机；只有当前服务支持时才会用于听写。">
          <div className="mgmt-grid-2">
            <OperationalList items={[
              { id: 'push-to-talk', title: '按住说话', detail: '按下开始、松开后形成最终文字', meta: hotkeyLabel(stringValue(valueAt(voiceControl, 'agent.hotkeyMode'), stringValue(voiceSettings.hotkey))), status: <StatusBadge label={booleanValue(voiceAgent.ok) ? '已就绪' : '待检查'} tone={booleanValue(voiceAgent.ok) ? 'success' : 'warning'} /> },
              { id: 'hotwords', title: '当前词表', detail: '控制中心与语音输入使用同一份本地词表', meta: `${savedHotwords.length} 条`, status: <StatusBadge label={hotwordApplyLabel(hotwordControl)} tone={hotwordApplyTone(hotwordControl)} /> },
            ]} />
            <div className="mgmt-stack">
              <Switch
                checked={hotwordsEnabled}
                description={hotwordsSupported
                  ? '关闭时保留词表，但不会随识别请求发送。'
                  : '当前转写服务不支持本次专有词；切换到支持此功能的实时听写服务后，可继续使用现有词表。'}
                disabled={!hotwordsSupported}
                label="启用热词"
                onCheckedChange={setHotwordsEnabled}
              />
              <label className="voice-hotword-editor">
                <span>每行一个词</span>
                <TextArea
                  aria-label="语音热词"
                  disabled={!hotwordsSupported}
                  onChange={(event) => setHotwordsText(event.target.value)}
                  placeholder={`例如：${identity.assistantName}`}
                  rows={7}
                  value={hotwordsText}
                />
                <small>{hotwordDraft.words.length} / 32 条，每个 2 至 9 个字符</small>
              </label>
              {hotwordDraft.error ? <InlineNotice title="词表需要调整" tone="warning">{hotwordDraft.error}</InlineNotice> : null}
              <div className="voice-hotword-suggestions" aria-label="热词建议">
                {suggestedHotwords.map((word) => (
                  <button disabled={!hotwordsSupported} key={word} onClick={() => addSuggestedHotword(word)} type="button">
                    <Plus size={12} aria-hidden="true" />
                    {word}
                  </button>
                ))}
              </div>
              <ManagementMutationWorkflow
                availability={mutationBoundary.availability(
                  !hotwordsSupported
                    ? '当前转写服务不支持本次专有词。'
                    : runtimeRevision === null
                    ? '当前语音设置尚未同步，刷新后才能继续保存。'
                    : hotwordDraft.error
                      ? '请先修正上方词表。'
                      : !hotwordDirty
                        ? '修改词表或启用状态后才能保存。'
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
                onApplied={reloadVoice}
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
                onRolledBack={reloadVoice}
                risk="R1"
                title="保存热词词表"
              />
              {!hotwordsSupported ? (
                <InlineNotice title={`${activeProvider.label} 不发送热词`} tone="info">
                  词表仍保存在本机；支持本次专有词的当前实时听写服务会在听写时使用它。
                </InlineNotice>
              ) : null}
            </div>
          </div>
        </ManagementSection>

        <ManagementSection title="文字定稿" description="让临时听写在结束后替换为完整文字，避免重复或半句话残留。">
          <div className="mgmt-grid-2">
            <div className="mgmt-stack">
              <Field
                description={
                  refinementModel === 'inherit'
                    ? `跟随伙伴默认模型${selectedRefinementModel ? `：${selectedRefinementModel.name}` : ''}`
                    : '只影响语音识别结束后的保守校对。'
                }
                htmlFor="voice-refinement-model"
                label="保守校对模型"
              >
                {queries.modelCatalogSupported && modelCatalog.models.length ? (
                  <Select
                    id="voice-refinement-model"
                    onValueChange={changeRefinementModel}
                    options={[
                      {
                        value: 'inherit',
                        label: selectedRefinementModel && refinementModel === 'inherit'
                          ? `跟随伙伴默认模型（${selectedRefinementModel.name}）`
                          : '跟随伙伴默认模型',
                      },
                      ...modelCatalog.models.map((model) => ({
                        value: model.reference,
                        label: `${model.name} (${model.reference})`,
                      })),
                    ]}
                    value={refinementModel}
                  />
                ) : (
                  <StatusBadge
                    label={queries.modelCatalogSupported ? '当前没有可用模型' : '暂时无法读取模型列表'}
                    tone="warning"
                  />
                )}
              </Field>
              <Field
                description="较低强度响应更快；这里只显示当前模型可用的选项。"
                htmlFor="voice-refinement-thinking"
                label="校对强度"
              >
                {queries.modelCatalogSupported && refinementThinkingLevels.length ? (
                  <Select
                    id="voice-refinement-thinking"
                    onValueChange={setRefinementThinking}
                    options={refinementThinkingLevels.map((level) => ({
                      value: level,
                      label: thinkingLabel(level),
                    }))}
                    value={refinementThinking}
                  />
                ) : (
                  <StatusBadge label="请先选择可用模型" tone="warning" />
                )}
              </Field>
            </div>
            <ManagementMutationWorkflow
              availability={mutationBoundary.availability(
                runtimeRevision === null
                  ? '当前语音设置尚未同步，刷新后才能继续保存。'
                  : !queries.modelCatalogSupported || !selectedRefinementModel
                    ? '当前无法确认保守校对模型，请刷新模型列表。'
                    : !refinementThinkingLevels.includes(refinementThinking)
                      ? '当前模型不支持所选校对强度。'
                      : !refinementDirty
                        ? '更改校对模型或校对强度后才能保存。'
                        : '',
              )}
              description="保存后下一次语音定稿立即使用；不影响普通对话、多人协作或闪电生成。"
              draftKey={JSON.stringify({
                model: refinementModel,
                thinking: refinementThinking,
                runtimeRevision,
              })}
              mutationKey={['voice', 'mutation', 'refinement']}
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
              onApplied={() => void queries.settings.refetch()}
              onPreview={async () => {
                if (
                  runtimeRevision === null
                  || !refinementDirty
                  || !selectedRefinementModel
                  || !refinementThinkingLevels.includes(refinementThinking)
                ) {
                  throw new Error('语音校对模型草案没有可应用的变化。');
                }
                const context = {
                  changes: {
                    'voice.refinementModel': refinementModel,
                    'voice.refinementThinkingLevel': refinementThinking,
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
              onRolledBack={() => void queries.settings.refetch()}
              risk="R1"
              title="保存保守校对模型"
            />
          </div>
          <Disclosure className="voice-refinement-status" summary="文字定稿状态">
            <div className="voice-refinement-status__content">
          <MetricStrip items={[
            { label: '引擎最终稿', value: finalRevisionLabel(deployedRecognition, lastRecognition, deployedRecognitionState), detail: '转写引擎会在结束时给出最终文字', icon: CheckCircle2, tone: deployedTone(deployedRecognition.secondPass) },
            { label: '保守校对', value: thirdPassLabel(deployedRecognition, lastRecognition, deployedRecognitionState), detail: thirdPassDetail(deployedRecognition, lastRecognition), icon: Sparkles, tone: thirdPassTone(deployedRecognition, lastRecognition) },
            { label: '替换临时文字', value: replacementLabel(deployedRecognition, lastRecognition, deployedRecognitionState), detail: '最终文字会替换临时稿，而不是继续追加', icon: Waves, tone: deployedTone(deployedRecognition.fullResultReplacement) },
            { label: '最近一次定稿', value: booleanValue(lastRecognition.finalReceived) ? '已收到' : '暂无验证', detail: providerResponseSummary(lastRecognition), icon: Mic, tone: booleanValue(lastRecognition.finalReceived) ? 'success' : 'warning' },
          ]} />
          {deployedRecognitionState !== 'ready' ? (
            <InlineNotice title={recognitionNoticeTitle(deployedRecognitionState)} tone="warning">
              {recognitionNoticeText(deployedRecognitionState)}
            </InlineNotice>
          ) : !booleanValue(lastRecognition.finalReceived) ? (
            <InlineNotice title="文字定稿等待首次验证" tone="info">
              文字定稿已经准备好；完成一次实际听写后，这里会显示真实定稿耗时。
            </InlineNotice>
          ) : booleanValue(lastRecognition.thirdPassApplied) ? (
            <InlineNotice title="已完成保守校对" tone="success">
              {thirdPassResultSummary(lastRecognition)}
            </InlineNotice>
          ) : booleanValue(lastRecognition.thirdPassRequested) ? (
            <InlineNotice title="保守校对没有完成，已保留引擎最终稿" tone="warning">
              {publicErrorText(lastRecognition.thirdPassError, '校对服务没有返回可安全采用的文字。')}
            </InlineNotice>
          ) : lastRecognition.finalRevisedPartial !== true && lastRecognition.localSmoothingApplied !== true ? (
            <InlineNotice title="引擎最终稿与临时稿相同" tone="info">
              {deployedRecognition.thirdPassRefinementEnabled === true
                ? '这次无需替换；下次遇到相同情况仍会进行一次独立的保守校对。'
                : '这次无需替换；保守校对当前关闭，将直接采用转写引擎的最终稿。'}
            </InlineNotice>
          ) : null}
          {booleanValue(lastRecognition.finalReceived) && stringValue(lastRecognition.providerResponseStage) ? (
            <Disclosure className="voice-recognition-details" summary="高级：本次定稿记录">
              <p>{providerMetadataDetail(lastRecognition)}</p>
            </Disclosure>
          ) : null}
            </div>
          </Disclosure>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

type VoiceCredentialDraft = Omit<VoiceCredentialSaveRequest, 'provider'> & {
  accessToken: string;
};

function defaultCredentialDraft(provider: VoiceProviderId): VoiceCredentialDraft {
  return {
    accessToken: '',
    appId: '',
    resourceId: 'volc.seedasr.sauc.duration',
    endpoint: provider === 'realtime_websocket'
      ? 'wss://api.openai.com/v1/realtime?intent=transcription'
      : provider === 'http_transcription'
        ? 'https://api.openai.com/v1/audio/transcriptions'
        : '',
    model: provider === 'native_streaming' ? '' : 'gpt-4o-mini-transcribe',
    headersJson: '',
  };
}

function validateCredentialDraft(
  provider: VoiceProviderId,
  draft: VoiceCredentialDraft,
): VoiceCredentialSaveRequest {
  const normalized = Object.fromEntries(
    Object.entries(draft).map(([key, value]) => [key, value.trim()]),
  ) as unknown as VoiceCredentialDraft;
  if (provider === 'native_streaming') {
    if (!normalized.appId || !normalized.resourceId) {
      throw new Error('当前实时听写服务需要填写应用编号和资源编号。');
    }
  } else {
    let endpoint: URL;
    try {
      endpoint = new URL(normalized.endpoint);
    } catch {
      throw new Error('请填写有效的转写服务地址。');
    }
    const acceptedSchemes = provider === 'realtime_websocket' ? ['ws:', 'wss:'] : ['http:', 'https:'];
    if (!acceptedSchemes.includes(endpoint.protocol) || !normalized.model) {
      throw new Error('转写服务地址或模型未填写完整。');
    }
  }
  if (normalized.headersJson) {
    let headers: unknown;
    try {
      headers = JSON.parse(normalized.headersJson);
    } catch {
      throw new Error('请求头必须是有效的 JSON。');
    }
    if (!isStringDictionary(headers)) throw new Error('请求头必须是字符串键值对象。');
  }
  return { provider, ...normalized };
}

function isStringDictionary(value: unknown): value is Record<string, string> {
  return typeof value === 'object'
    && value !== null
    && !Array.isArray(value)
    && Object.values(value).every((item) => typeof item === 'string');
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

function thinkingLabel(value: string): string {
  return ({
    off: '关闭',
    minimal: '极低',
    low: '低',
    medium: '中',
    high: '高',
    xhigh: '很高',
    max: '最高',
  } as Record<string, string>)[value] ?? value;
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

function deployedLabel(value: unknown, state = 'unchecked'): string {
  if (state === 'missing') return '尚未安装';
  if (state === 'restart_required') return value === true ? '待重启生效' : '待重启检查';
  if (state === 'outdated') return value === true ? '当前可用' : '安装版本过旧';
  if (state === 'unsupported') return value === true ? '当前可用' : '运行版本不完整';
  if (state === 'unreadable') return '读取失败';
  if (value === true) return '当前可用';
  if (value === false) return '当前不可用';
  return '未检查';
}

function deployedTone(value: unknown): VoiceStatusTone {
  if (value === true) return 'success';
  if (value === false) return 'warning';
  return 'neutral';
}

function finalRevisionLabel(
  deployed: Record<string, unknown>,
  last: Record<string, unknown>,
  state: string,
): string {
  if (!booleanValue(last.finalReceived)) return requestedCapabilityLabel(deployed.secondPass, state);
  return booleanValue(last.providerFinalRevisedPartial) ? '服务返回了修订稿' : '最终稿无变化';
}

function thirdPassLabel(
  deployed: Record<string, unknown>,
  last: Record<string, unknown>,
  state: string,
): string {
  if (deployed.thirdPassRefinementEnabled === false) return '已关闭';
  if (booleanValue(last.thirdPassApplied)) {
    return booleanValue(last.thirdPassChanged) ? '本次已纠错' : '本次无需改动';
  }
  if (booleanValue(last.thirdPassRequested)) return '本次执行失败';
  if (booleanValue(last.finalReceived)) return '本次未触发';
  return enabledCapabilityLabel(deployed.thirdPassRefinement, state) === '已启用'
    ? '已启用，等待触发'
    : deployedLabel(deployed.thirdPassRefinement, state);
}

function thirdPassDetail(
  deployed: Record<string, unknown>,
  last: Record<string, unknown>,
): string {
  if (deployed.thirdPassRefinementEnabled === false) {
    return '关闭后直接采用转写引擎的最终稿';
  }
  if (booleanValue(last.thirdPassApplied)) {
    const latency = durationLabel(last.thirdPassLatencyMs);
    const model = stringValue(last.thirdPassModel);
    return model ? `${latency} · ${model}` : latency;
  }
  if (booleanValue(last.thirdPassRequested)) return '失败时保留引擎最终稿，不影响已输入文字';
  return '最终稿与临时稿相同时，再做一次独立的保守校对';
}

function thirdPassTone(
  deployed: Record<string, unknown>,
  last: Record<string, unknown>,
): VoiceStatusTone {
  if (deployed.thirdPassRefinementEnabled === false) return 'neutral';
  if (booleanValue(last.thirdPassApplied)) return 'success';
  if (booleanValue(last.thirdPassRequested)) return 'warning';
  return deployedTone(deployed.thirdPassRefinement);
}

function replacementLabel(
  deployed: Record<string, unknown>,
  last: Record<string, unknown>,
  state: string,
): string {
  if (!booleanValue(last.finalReceived)) return enabledCapabilityLabel(deployed.fullResultReplacement, state);
  return booleanValue(last.finalRevisedPartial) ? '本次已替换' : '本次无需替换';
}

function requestedCapabilityLabel(value: unknown, state: string): string {
  const label = deployedLabel(value, state);
  return label === '当前可用' ? '已请求' : label;
}

function enabledCapabilityLabel(value: unknown, state: string): string {
  const label = deployedLabel(value, state);
  return label === '当前可用' ? '已启用' : label;
}

function recognitionNoticeTitle(state: string): string {
  if (state === 'missing') return '尚未安装听写服务';
  if (state === 'restart_required') return '安装已更新，听写服务需要重启';
  if (state === 'outdated') return '听写服务版本过旧';
  if (state === 'unreadable') return '无法读取听写服务';
  if (state === 'unsupported') return '运行中的听写服务能力不完整';
  return '定稿能力尚未完成检查';
}

function recognitionNoticeText(state: string): string {
  if (state === 'restart_required') return '新版本已经包含完整的文字定稿能力；重启听写服务后再刷新此页。';
  if (state === 'outdated') return '当前版本缺少完整的临时文字替换能力，请更新听写服务。';
  if (state === 'missing') return '没有找到听写组件。完成应用安装后，再检查麦克风与辅助功能权限。';
  if (state === 'unreadable') return '听写组件存在，但暂时无法确认它的版本；请重新安装后再试。';
  if (state === 'unsupported') return '正在运行的听写服务缺少完整定稿能力，请更新并重启应用。';
  return '刷新后仍无法确认听写服务的文字定稿能力。';
}

function finalLatencyLabel(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return '尚无实际听写数据';
  }
  return `定稿用时 ${Math.round(value)} 毫秒`;
}

function durationLabel(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return '耗时未记录';
  }
  return `${Math.round(value)} 毫秒`;
}

function providerResponseSummary(last: Record<string, unknown>): string {
  const latency = finalLatencyLabel(last.finalLatencyMs);
  const count = typeof last.providerResponseCount === 'number' ? last.providerResponseCount : 0;
  if (!stringValue(last.providerResponseStage)) return latency;
  return `${latency}${count > 0 ? ` · 收到 ${count} 次服务返回` : ''}`;
}

function providerMetadataDetail(last: Record<string, unknown>): string {
  const stages = stringArray(last.providerResponseStages);
  const utterances = Array.isArray(last.providerUtteranceMetadata)
    ? last.providerUtteranceMetadata.length
    : 0;
  const additions = Object.keys(asRecord(last.providerAdditionFields));
  const stageCount = stages.length || (stringValue(last.providerResponseStage) ? 1 : 0);
  const additionalInformation = additions.length > 0 ? '；服务返回了额外信息' : '';
  return `本次处理经过 ${stageCount} 个阶段；识别到 ${utterances} 个语句片段${additionalInformation}。听写正文不会写入诊断记录。`;
}

function thirdPassResultSummary(last: Record<string, unknown>): string {
  const changed = booleanValue(last.thirdPassChanged)
    ? '独立校对稿已替换服务最终稿'
    : '独立校对确认无需修改';
  const latency = durationLabel(last.thirdPassLatencyMs);
  const model = stringValue(last.thirdPassModel);
  return `${changed}；耗时 ${latency}${model ? `；模型 ${model}` : ''}。`;
}
