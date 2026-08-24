export function publicMemoryText(value: string): string {
  return value
    .replace(/参与召回/gu, '用于联想')
    .replace(/召回正文/gu, '联想内容')
    .replace(/召回/gu, '联想');
}

// One provenance vocabulary for every Memory surface. The catalog and the
// relation views must never disagree about where the same record came from.
export function publicMemorySourceLabel(source: string, assistantName = ''): string {
  const normalized = source.toLocaleLowerCase('en-US');
  if (!normalized || normalized === 'local') return '本地记忆';
  if (normalized.includes('input_app')) return '应用上下文';
  if (normalized === 'smart' || normalized.includes('dsv4') || normalized.includes('deepseek')) return '智能整理';
  if (normalized.includes('user')) return '用户编辑';
  if (normalized.includes('import')) return '导入';
  if (normalized.includes('notion')) return 'Notion';
  if (normalized.includes('rime') || normalized.includes('input')) return '输入记录';
  if (normalized.includes('agent') || normalized.includes('pi')) return `${assistantName || '伙伴'}整理`;
  if (normalized.includes('manual')) return '手动整理';
  if (normalized.includes('sqlite') || normalized.includes('memory_')) return '本地记忆';
  return '其他来源';
}

export function publicMemoryOwnerLabel(
  ownerKind: string,
  ownerId: string,
  ownerName = '',
): string {
  if (!ownerKind || !ownerId) return '';
  if (ownerKind === 'user' && ownerId === 'default') return '个人记忆';
  if (ownerKind === 'shared' && ownerId === 'default') return '全局共享';

  const category = ({
    agent: '伙伴记忆',
    room: '协作记忆',
    session: '对话记忆',
    shared: '项目共享',
    user: '个人记忆',
  } as Record<string, string>)[ownerKind] ?? '其他归属';
  const name = publicMemoryText(ownerName.trim());
  return name && name !== ownerId ? `${category} · ${name}` : category;
}
