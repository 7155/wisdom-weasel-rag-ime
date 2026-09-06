import { useId } from 'react';
import { Disclosure, Field, Input, TextArea } from '@/components/primitives';
import { goldenThinkingLevels, isGoldenThinkingLevel, type GoldenEvidence, type GoldenSource, type ModelConfig } from './types';

export function ModelFields({ label, value, onChange, disabled = false }: {
  label: string; value: ModelConfig; onChange: (value: ModelConfig) => void; disabled?: boolean;
}) {
  const id = useId();
  const validThinking = isGoldenThinkingLevel(value.thinkingLevel);
  const promptLabel = label === '评审' ? '评审规则' : `${label}回答规则`;
  return <fieldset className="golden-model" disabled={disabled}>
    <legend>{label}</legend>
    <div className="golden-model__fields">
      <Field htmlFor={`${id}-provider`} label={`${label}服务`} required>
        <Input id={`${id}-provider`} value={value.provider} required aria-invalid={!value.provider.trim() || undefined} placeholder="填写服务标识" onChange={(event) => onChange({ ...value, provider: event.target.value })} />
      </Field>
      <Field htmlFor={`${id}-model`} label={`${label}模型`} required>
        <Input id={`${id}-model`} value={value.model} required aria-invalid={!value.model.trim() || undefined} placeholder="填写模型名称" onChange={(event) => onChange({ ...value, model: event.target.value })} />
      </Field>
      <Field htmlFor={`${id}-thinking`} label={`${label}推理强度`} required>
        <select id={`${id}-thinking`} value={value.thinkingLevel} required aria-invalid={!validThinking || undefined} onChange={(event) => onChange({ ...value, thinkingLevel: event.target.value })}>
          <option value="" disabled>请选择推理强度</option>
          {value.thinkingLevel && !validThinking ? <option value={value.thinkingLevel} disabled>不支持：{value.thinkingLevel}</option> : null}
          {goldenThinkingLevels.map((level) => <option key={level} value={level}>{level}</option>)}
        </select>
      </Field>
    </div>
    {!value.provider.trim() || !value.model.trim() || !validThinking ? <p className="golden-field-error" role="status">请填写明确的服务、模型，并选择支持的推理强度。</p> : null}
    <Disclosure className="golden-disclosure" summary={`${promptLabel}（Prompt）`}>
      <Field htmlFor={`${id}-prompt`} label={promptLabel}>
        <TextArea id={`${id}-prompt`} value={value.prompt} rows={5} placeholder={label === '评审' ? '可补充评审规则；留空使用固定评审协议' : '可补充回答规则；留空使用任务自带规则'} onChange={(event) => onChange({ ...value, prompt: event.target.value })} />
      </Field>
    </Disclosure>
  </fieldset>;
}

export function EvidenceView({ evidence, sources }: { evidence: GoldenEvidence[]; sources: GoldenSource[] }) {
  if (!evidence.length) return <p className="golden-note">未附引用证据。</p>;
  return <div className="golden-evidence">
    {evidence.map((item, index) => {
      const source = sources.find((source) => source.sourceId === item.sourceId);
      return <figure key={`${item.sourceId}:${index}`}>
        <blockquote>{item.quote}</blockquote>
        <figcaption>{source?.title ?? '来源不可用'}{source?.uri ? <span> · {source.uri}</span> : null}</figcaption>
      </figure>;
    })}
  </div>;
}

export function formatRate(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toLocaleString('zh-CN', { maximumFractionDigits: 1 })}%` : '未提供';
}
export function formatTime(value: number): string {
  return new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
