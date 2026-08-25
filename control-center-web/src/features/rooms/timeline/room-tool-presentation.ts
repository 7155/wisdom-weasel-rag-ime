import type {
  PublicToolRequestField,
  PublicToolResultField,
  PublicToolResultView,
} from '@/features/agent/timeline/public-tool-result';

const technicalFieldName = /(?:^|[._-])(?:actor|block|command|commit|dispatch|event|generation|hash|id|participant|receipt|ref|revision|root|schema(?:version)?|session|sha\d*|task|token|turn)(?:$|[._-])/iu;
const technicalFieldLabel = /(?:回执|哈希|内部标识|会话标识|分派标识|协议版本)/u;
const technicalLine = /(?:receipt(?:Id)?|contentHash|payloadHash|outputHash|artifactHash|schemaVersion|dispatchId|rootId|taskId|turnId|sessionId|toolCallId|toolId|pathId)\s*(?:=|:)/iu;
const internalProtocolTerm = /\b(?:Kernel|Root|Dispatch|Task|AC|Receipt\s+ID)\b/giu;
const protocolReference = /\b(?:actor|block|call|command|dispatch|event|message|participant|post|receipt|room|root|session|task|tool|turn)[-_:][A-Za-z0-9_.:-]{4,}\b/giu;
const contentHash = /\b(?:sha(?:1|224|256|384|512):)?[a-f0-9]{32,}\b/giu;
const uuid = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/giu;
const absolutePosixPath = /(^|[\s"'`=(])\/(?:Users|Volumes|private|var|tmp|home|opt|workspace|mnt)\/(?:[^/\n"'`),;]+\/)*[^/\s"'`),;]+/gmu;
const absoluteWindowsPath = /\b[A-Za-z]:\\(?:[^\\\s"'`]+\\)*[^\\\s"'`]+/gu;
const semanticReferenceFieldIds: Record<string, true> = {
  stateRevision: true,
  evidenceRef: true,
  targetParticipantRef: true,
  postRef: true,
};
const hiddenTechnicalFieldIds: Record<string, true> = {
  canonicalTool: true,
  created: true,
  deduplicated: true,
  enqueued: true,
  settlementStaged: true,
  terminalForModelTurn: true,
};

/**
 * Room history is a user-facing explanation, not the protocol inspector.
 * Keep useful, semantic tool details while leaving durable machine evidence in
 * the underlying activity projection.
 */
export function roomPublicToolResultView(view: PublicToolResultView): PublicToolResultView {
  const fields = view.fields.flatMap((field) => sanitizeField(field));
  const request = view.request.flatMap((field) => sanitizeRequestField(field));
  // A 变更差异 body is structural: the upstream projection already redacted
  // secrets and machine paths, and the line-oriented sanitizer would break
  // the unified-diff format the shared diff reader needs (PF-CM-004/008).
  const structuralOutput = view.outputLabel === '变更差异';
  const outputText = view.output
    ? structuralOutput
      ? view.output.text
      : sanitizeOutput(view.output.text)
    : '';
  const summary = sanitizeText(view.summary) || `${view.toolLabel}已完成`;
  const error = view.error ? sanitizeText(view.error) : '';
  const sources = view.sources.map(sanitizeText).filter(Boolean);
  const resultItems = view.resultItems.flatMap((item) => {
    const label = sanitizeText(item.label);
    const text = sanitizeText(item.text);
    if (!label && !text) return [];
    return [{ ...item, label, text }];
  });
  const preview = view.preview
    ? {
        ...view.preview,
        title: sanitizeText(view.preview.title) || '工具结果',
        ...(view.preview.description && sanitizeText(view.preview.description)
          ? { description: sanitizeText(view.preview.description) }
          : {}),
        badges: view.preview.badges.map(sanitizeText).filter(Boolean),
        items: view.preview.items.flatMap((item) => {
          const text = sanitizeText(item.text);
          if (!text) return [];
          const label = item.label ? sanitizeText(item.label) : '';
          return [{
            id: item.id,
            text,
            ...(label ? { label } : {}),
            ...(item.href ? { href: item.href } : {}),
          }];
        }),
      }
    : undefined;

  return {
    toolId: view.toolId,
    toolLabel: view.toolLabel,
    operation: view.operation,
    summary,
    resultKind: view.resultKind,
    resultItems,
    fields,
    request,
    sources,
    ...(view.target && sanitizePath(view.target) ? { target: sanitizePath(view.target) } : {}),
    ...(view.change ? { change: view.change } : {}),
    ...(view.language ? { language: view.language } : {}),
    ...(preview ? { preview } : {}),
    ...(outputText && view.output
      ? {
          output: { ...view.output, text: outputText },
          ...(view.outputLabel ? { outputLabel: view.outputLabel } : {}),
        }
      : {}),
    ...(error ? { error } : {}),
    ...(view.recovery ? { recovery: view.recovery } : {}),
    ...(view.destination ? { destination: view.destination } : {}),
  };
}

export function roomPublicActivityText(value: string): string {
  return sanitizeText(value);
}

export function roomPublicActivityOutput(value: string): string {
  return sanitizeOutput(value);
}

function sanitizeField(field: PublicToolResultField): PublicToolResultField[] {
  if (isTechnicalField(field)) return [];
  const value = semanticReferenceFieldIds[field.id] === true
    ? semanticReferenceValue(field.id, field.value)
    : field.id === 'file' || field.id === 'path'
      ? sanitizePath(field.value)
      : sanitizeText(field.value);
  return value ? [{ ...field, value }] : [];
}

function sanitizeRequestField(field: PublicToolRequestField): PublicToolRequestField[] {
  if (field.id === 'command' || isTechnicalField(field)) return [];
  const value = semanticReferenceFieldIds[field.id] === true
    ? semanticReferenceValue(field.id, field.value)
    : field.id === 'file' || field.id === 'path'
      ? sanitizePath(field.value)
      : sanitizeText(field.value);
  return value ? [{ ...field, value }] : [];
}

function isTechnicalField(field: PublicToolResultField): boolean {
  if (
    field.id === 'file'
    || field.id === 'path'
    || semanticReferenceFieldIds[field.id] === true
  ) return false;
  return hiddenTechnicalFieldIds[field.id] === true
    || technicalFieldName.test(field.id)
    || technicalFieldLabel.test(field.label);
}

function semanticReferenceValue(id: string, value: string): string {
  if (!value.trim()) return '';
  if (id === 'stateRevision') {
    const revision = value.match(/\d+/u)?.[0];
    return revision ? `第 ${revision} 版` : '协作状态已更新';
  }
  if (id === 'evidenceRef') return '验证依据已保留';
  if (id === 'targetParticipantRef') return '目标伙伴已确认';
  return '公开记录已保留';
}

function sanitizeOutput(value: string): string {
  if (isRawJson(value)) return '';
  return value
    .replace(/\r\n?/gu, '\n')
    .split('\n')
    .flatMap((line) => {
      if (technicalLine.test(line) || isRawJson(line)) return [];
      const safe = sanitizeText(line);
      return safe ? [safe] : [];
    })
    .join('\n')
    .trim();
}

function sanitizeText(value: string): string {
  const normalized = value.trim();
  if (!normalized || technicalLine.test(normalized) || isRawJson(normalized)) return '';
  return normalized
    .replace(absolutePosixPath, (_match, prefix: string) => `${prefix}…/${fileName(_match.slice(prefix.length))}`)
    .replace(absoluteWindowsPath, (match) => `…/${fileName(match)}`)
    .replace(contentHash, '已隐藏的校验值')
    .replace(uuid, '已隐藏的记录')
    .replace(protocolReference, '协作记录')
    .replace(internalProtocolTerm, naturalProtocolTerm)
    .replace(/\s*(协作系统|协作记录|本轮工作|执行安排|工作项|验收标准|验证记录)\s*/gu, '$1')
    .trim();
}

function naturalProtocolTerm(value: string): string {
  const normalized = value.toLocaleLowerCase('en-US').replace(/\s+/gu, ' ');
  if (normalized === 'kernel') return '协作系统';
  if (normalized === 'root') return '本轮工作';
  if (normalized === 'dispatch') return '执行安排';
  if (normalized === 'task') return '工作项';
  if (normalized === 'ac') return '验收标准';
  return '验证记录';
}

function sanitizePath(value: string): string {
  const normalized = value.trim();
  if (!normalized) return '';
  if (/^(?:\/(?:Users|Volumes|private|var|tmp|home|opt|workspace|mnt)\/|[A-Za-z]:\\)/u.test(normalized)) {
    return fileName(normalized);
  }
  return sanitizeText(normalized);
}

function fileName(value: string): string {
  return value.replace(/[\\/]+$/u, '').split(/[\\/]/u).filter(Boolean).at(-1) ?? '';
}

function isRawJson(value: string): boolean {
  const normalized = value.trim();
  if (/^```json\b/iu.test(normalized)) return true;
  if (!normalized.startsWith('{') && !normalized.startsWith('[')) return false;
  try {
    const parsed: unknown = JSON.parse(normalized);
    return Boolean(parsed) && typeof parsed === 'object';
  } catch {
    return /^(?:\{|\[).*"[^"\n]+"\s*:/su.test(normalized);
  }
}
