import type { AgentExecutionMode } from '../composer/agent-preferences-store';

/**
 * Conversation chrome marks — the identity layer the composer and the Session
 * lead-in fall back to when the window is too narrow for their labels.
 *
 * A mark is an original PAW silhouette that carries the *semantic* cue of a
 * permission mode or a model-provider family. It is deliberately not a vendor
 * trademark reproduction: PF-CM-019 forbids copying another product's brand
 * artwork, and PF-CM-006 keeps identity in silhouette plus colour family
 * rather than in a shared tile. Recognition therefore comes from contour first
 * and hue second, and every placement still carries the real label through
 * `aria-label`/`title` even when the text is visually collapsed.
 */

export type PermissionMarkKind =
  | 'read-only'
  | 'per-action'
  | 'workspace'
  | 'full-trust';

export type ProviderMarkKind =
  | 'openai'
  | 'anthropic'
  | 'google'
  | 'deepseek'
  | 'qwen'
  | 'moonshot'
  | 'zhipu'
  | 'xai'
  | 'mistral'
  | 'local'
  | 'router'
  | 'generic';

export function permissionMarkKind(
  mode: AgentExecutionMode | string | undefined | null,
): PermissionMarkKind {
  if (mode === 'read_only') return 'read-only';
  if (mode === 'workspace_managed') return 'workspace';
  if (mode === 'full_trust') return 'full-trust';
  return 'per-action';
}

/** Ordered because several vendor names are substrings of each other —
 *  `ollama` contains `llama`, `openai-codex` contains both `openai` and
 *  `codex`, and aggregator ids often embed the upstream vendor name. The
 *  first rule that matches the joined `id + displayName` wins. */
const PROVIDER_RULES: ReadonlyArray<{ kind: ProviderMarkKind; test: RegExp }> = [
  { kind: 'local', test: /ollama|lm[\s_-]?studio|llama[.\s_-]?cpp|llamacpp|vllm|sglang|localai|koboldcpp|\blocal\b|本地|本机/u },
  { kind: 'router', test: /openrouter|open[\s_-]router|litellm|one[\s_-]?api|new[\s_-]?api|siliconflow|硅基流动|aihubmix/u },
  { kind: 'openai', test: /openai|chatgpt|\bgpt\b|gpt-|codex|azure/u },
  { kind: 'anthropic', test: /anthropic|claude/u },
  { kind: 'google', test: /google|gemini|vertex|palm|谷歌/u },
  { kind: 'deepseek', test: /deepseek|深度求索/u },
  { kind: 'qwen', test: /qwen|tongyi|通义|dashscope|bailian|百炼|alibaba|aliyun|阿里/u },
  { kind: 'moonshot', test: /moonshot|kimi|月之暗面/u },
  { kind: 'zhipu', test: /zhipu|智谱|\bglm\b|chatglm|bigmodel/u },
  { kind: 'xai', test: /\bxai\b|x\.ai|grok/u },
  { kind: 'mistral', test: /mistral|codestral|magistral/u },
];

export function providerMarkKind(
  providerId: string | undefined | null,
  displayName?: string | null,
): ProviderMarkKind {
  const haystack = `${providerId ?? ''} ${displayName ?? ''}`.toLowerCase();
  if (!haystack.trim()) return 'generic';
  return PROVIDER_RULES.find((rule) => rule.test.test(haystack))?.kind ?? 'generic';
}

/**
 * The generic mark still has to say *which* unknown provider it stands for, so
 * it carries an initial rather than an anonymous placeholder. CJK names read
 * best as a single glyph; Latin names keep up to two letters.
 */
export function providerMarkInitial(
  providerId: string | undefined | null,
  displayName?: string | null,
): string {
  const source = (displayName || providerId || '').trim();
  const cjk = source.match(/[\u3400-\u9fff]/u);
  if (cjk) return cjk[0];
  const latin = source.replace(/[^a-zA-Z0-9]+/gu, '');
  if (!latin) return '·';
  return latin.slice(0, 2).toUpperCase();
}
