export function publicMemoryText(value: string): string {
  return value
    .replace(/参与召回/gu, '用于联想')
    .replace(/召回正文/gu, '联想内容')
    .replace(/召回/gu, '联想');
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
