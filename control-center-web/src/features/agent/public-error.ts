import { publicErrorText } from '@/features/overview/management-ui';

const unavailableModelPattern = /(?:model\s+["']?[^"']+["']?\s+is\s+not\s+supported|unsupported\s+model|model_not_supported|模型.*(?:不支持|不可用))/i;

export function publicAgentErrorText(
  value: unknown,
  fallback = '本轮没有完成，请重试或切换模型。',
): string {
  const message = (value instanceof Error ? value.message : String(value ?? '')).trim();
  if (unavailableModelPattern.test(message)) {
    return '当前模型不可用，请切换模型后重试。';
  }
  return publicErrorText(value, fallback);
}
