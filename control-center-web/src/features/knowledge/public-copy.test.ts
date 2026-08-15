import { describe, expect, it } from 'vitest';
import {
  publicKnowledgeRelationKind,
  publicKnowledgeRelationLabel,
  publicKnowledgeText,
} from './public-copy';

describe('knowledge public copy', () => {
  it('turns backend-facing product terms into user-facing language', () => {
    expect(publicKnowledgeText('Agent Runtime / Agent Tool / Knowledge Worker / Tool')).toBe(
      '伙伴运行环境 / 伙伴工具 / 知识整理服务 / 工具',
    );
  });

  it('maps relation contract values without echoing unknown values', () => {
    expect(publicKnowledgeRelationKind('contains')).toBe('包含');
    expect(publicKnowledgeRelationKind('mentions')).toBe('提及');
    expect(publicKnowledgeRelationKind('next_chunk')).toBe('下一段');
    expect(publicKnowledgeRelationKind('internal_relation_v2')).toBe('其他关系');
    expect(publicKnowledgeRelationLabel('internal_relation_v2', 'internal_relation_v2')).toBe('其他关系');
  });
});
