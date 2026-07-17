import { publicErrorText } from '@/features/overview/management-ui';

const unavailableModelPattern = /(?:model\s+["']?[^"']+["']?\s+is\s+not\s+supported|unsupported\s+model|model_not_supported|模型.*(?:不支持|不可用))/i;
const providerRequestFailurePattern = /(?:error\s+from\s+provider|upstream\s+request\s+failed|provider[_\s-](?:request|response|error)|模型服务.*(?:失败|异常))/i;
const nativeRouteMismatchPattern = /(?:route[_\s-]policy[_\s-]rejected|unexpected\s+(?:request\s+)?body\s+field|body\s+field\s+is\s+not\s+allowlisted|unknown\s+pathid)/i;

export function publicAgentErrorText(
  value: unknown,
  fallback = '本轮没有完成，请重试或切换模型。',
): string {
  const message = (value instanceof Error ? value.message : String(value ?? '')).trim();
  if (unavailableModelPattern.test(message)) {
    return '当前模型不可用，请切换模型后重试。';
  }
  if (providerRequestFailurePattern.test(message)) {
    return '模型服务请求失败，请重试或切换模型。';
  }
  if (nativeRouteMismatchPattern.test(message)) {
    return '控制中心组件版本不一致，请更新并重新打开控制中心。';
  }
  return publicErrorText(value, fallback);
}
