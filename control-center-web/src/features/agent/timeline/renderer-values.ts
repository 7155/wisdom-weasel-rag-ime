export function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

export function finiteNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

export function displayScalar(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (value === null) return '—';
  return '';
}

export function safeLabelValuePairs(
  value: unknown,
): Array<{ label: string; value: string }> {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const field = record(item);
      return {
        label: text(field.label ?? field.name),
        value: displayScalar(field.value),
      };
    })
    .filter((field) => field.label && field.value)
    .slice(0, 24);
}

export function publicStructuredValue(value: string): string {
  const normalized = value.trim();
  const known = ({
    ready: '可用',
    running: '进行中',
    waiting: '等待确认',
    completed: '已完成',
    failed: '失败',
    approved: '已批准',
    rejected: '已拒绝',
    R0: '只读',
    R1: '需要确认',
    R2: '谨慎确认',
    R3: '高风险',
  } as Record<string, string>)[normalized];
  if (known) return known;
  return /^[a-z][a-z0-9_.:/-]*$/i.test(normalized) ? '已记录' : normalized;
}
