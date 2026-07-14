import { KeyRound, Mic, RefreshCw, Shield, Waves } from 'lucide-react';
import { useState } from 'react';
import { Button, SegmentedControl } from '@/components/primitives';
import { useVoiceQueries } from './api';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  WorkflowAction,
  asRecord,
  booleanValue,
  configuredLabel,
  stringValue,
  valueAt,
} from '@/features/overview/management-ui';

const providers = [
  { value: 'native-streaming', label: '原生流式' },
  { value: 'realtime-websocket', label: 'Realtime WS' },
  { value: 'http-transcription', label: 'HTTP 转写' },
] as const;

export function VoiceFeature() {
  const queries = useVoiceQueries();
  const settings = asRecord(asRecord(queries.settings.data).settings);
  const runtime = asRecord(queries.runtime.data);
  const components = asRecord(runtime.components);
  const voiceSettings = asRecord(settings.voice);
  const [provider, setProvider] = useState<(typeof providers)[number]['value']>(
    (providers.some((item) => item.value === stringValue(voiceSettings.provider))
      ? stringValue(voiceSettings.provider)
      : 'native-streaming') as (typeof providers)[number]['value'],
  );
  const tokenState = configuredLabel(
    voiceSettings.tokenConfigured ?? voiceSettings.accessTokenConfigured ?? valueAt(settings, 'voice.credentials.configured'),
  );
  const microphone = asRecord(components.microphone ?? components.voiceMicrophone);
  const accessibility = asRecord(components.accessibility ?? components.voiceAccessibility);
  const error = [queries.settings.error, queries.runtime.error, queries.capabilities.error].find(Boolean) as Error | null;
  const pending = queries.settings.isPending || queries.runtime.isPending || queries.capabilities.isPending;
  const refresh = () => void Promise.all([queries.settings.refetch(), queries.schema.refetch(), queries.runtime.refetch()]);

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={queries.runtime.isFetching} onClick={refresh} size="small">刷新</Button>}
      description="管理语音 Provider、按住说话热键、权限、隐私和运行诊断。"
      eyebrow="AUDIO"
      routeId="voice"
      title="语音输入"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="运行与隐私">
          <MetricStrip items={[
            { label: '语音 Agent', value: stringValue(asRecord(components.voiceAgent).status, 'unknown'), detail: '独立受控进程', icon: Waves, tone: booleanValue(asRecord(components.voiceAgent).ok) ? 'success' : 'warning' },
            { label: '麦克风', value: booleanValue(microphone.ok) ? 'allowed' : 'unknown', detail: 'TCC', icon: Mic, tone: booleanValue(microphone.ok) ? 'success' : 'warning' },
            { label: '辅助功能', value: booleanValue(accessibility.ok) ? 'allowed' : 'unknown', detail: '光标写入', icon: Shield, tone: booleanValue(accessibility.ok) ? 'success' : 'warning' },
            { label: '访问凭据', value: tokenState, detail: '安全存储', icon: KeyRound, tone: tokenState === 'configured' ? 'success' : 'warning' },
          ]} />
          <InlineNotice title="密钥边界" tone="info">已保存的 Token、Header 与 API Key 永不回显。本页只显示 configured / not configured。</InlineNotice>
        </ManagementSection>

        <ManagementSection title="Provider 与热键" description="查看当前语音服务、热键与热词设置。">
          <div className="mgmt-grid-2">
            <div className="mgmt-stack">
              <strong style={{ fontSize: 12 }}>语音 Provider</strong>
              <SegmentedControl aria-label="语音 Provider" items={providers} onValueChange={setProvider} value={provider} />
            </div>
            <OperationalList items={[
              { id: 'push-to-talk', title: '按住说话', detail: '按下开始、松开定稿，不与输入法候选键冲突', meta: stringValue(voiceSettings.hotkey, 'middle-mouse'), status: <StatusBadge label="local" tone="info" /> },
              { id: 'hotwords', title: '热词', detail: '只传递给受控 ASR Provider', meta: `${Array.isArray(voiceSettings.hotwords) ? voiceSettings.hotwords.length : 0} 条`, status: <StatusBadge label={booleanValue(voiceSettings.hotwordsEnabled) ? 'enabled' : 'disabled'} tone={booleanValue(voiceSettings.hotwordsEnabled) ? 'success' : 'neutral'} /> },
            ]} />
          </div>
        </ManagementSection>

        <ManagementSection title="受控配置" description="以下设置变更当前为演练，不会修改系统配置。">
          <div className="mgmt-grid-2">
            <WorkflowAction
              actionId="voice.provider.save"
              description="预览 Provider、模型与访问凭据状态的变化。"
              mutationKey={['voice', 'mutation', 'provider']}
              preview={[
                `目标 Provider：${provider}`,
                `当前凭据：${tokenState}`,
                'Token 与自定义 Header 不进入 receipt、日志或 VITE_*。',
              ]}
              risk="R2"
              title="更新语音配置"
            />
            <WorkflowAction
              actionId="voice.hotkey.save"
              description="切换按住说话热键并通知 Voice Agent 重载。"
              mutationKey={['voice', 'mutation', 'hotkey']}
              preview={[
                '默认 middle mouse：按住录音，松开定稿。',
                '变更不能占用 Rime 普通数字键与 Tab 候选操作。',
                '失败时保留旧热键。',
              ]}
              risk="R1"
              title="应用热键草案"
            />
          </div>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}
